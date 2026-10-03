from __future__ import annotations

import multiprocessing
import re
import subprocess
from concurrent.futures import ProcessPoolExecutor

import pytest

from susa.utilities.networking import (
    SUBNETS,
    free_subnet,
    host_subnets,
    ping,
    random_mac,
)


def test_ping() -> None:
    single = ping("127.0.0.1")
    assert isinstance(single, float)

    # The timeout is for the whole run.
    multiple = ping("127.0.0.1", 3, timeout=5, interval=1)
    assert len(multiple) == 3
    assert all(isinstance(time, float) for time in multiple)

    # 10.255.255.1 is a non-routable address, so no replies should come back.
    assert ping("10.255.255.1", 2) == [None, None]

    with pytest.raises(subprocess.CalledProcessError):
        ping("nonexistent.invalid")


def test_random_mac() -> None:
    mac = random_mac()
    assert re.fullmatch(r"[0-9a-f]{2}(:[0-9a-f]{2}){5}", mac)


@pytest.mark.parametrize("prefix", ("52", "52:54:00", "52:54:00:12:34"))
def test_random_mac_prefix(prefix: str) -> None:
    mac = random_mac(prefix)
    assert mac.startswith(prefix + ":")
    assert re.fullmatch(r"[0-9a-f]{2}(:[0-9a-f]{2}){5}", mac)


def test_random_mac_full_prefix() -> None:
    assert random_mac("52:54:00:12:34:56") == "52:54:00:12:34:56"


def test_free_subnet() -> None:
    subnet = free_subnet()
    assert subnet.prefixlen == 24 and subnet.subnet_of(SUBNETS)
    assert not any(subnet.overlaps(other) for other in host_subnets())
    # Taken by this process.
    assert free_subnet() != subnet
    # And by others, in parallel.
    with ProcessPoolExecutor(4, multiprocessing.get_context("spawn")) as pool:
        subnets = {subnet, *(pool.submit(free_subnet).result() for _ in range(4))}
    assert len(subnets) == 5
