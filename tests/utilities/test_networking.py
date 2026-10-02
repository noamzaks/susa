from __future__ import annotations

import ipaddress
import multiprocessing
import os
import re
import subprocess
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pytest

from susa.utilities import networking
from susa.utilities.networking import ping, random_mac


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


@pytest.fixture
def reservations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(networking, "RESERVATIONS", tmp_path)
    return tmp_path


def reserve(_: int) -> ipaddress.IPv4Network:
    subnet = networking.reserve_subnet()
    # Still alive (holding it) while the others reserve.
    time.sleep(1)
    return subnet


def test_reserve_subnet_in_parallel(reservations: Path) -> None:
    with ProcessPoolExecutor(4, multiprocessing.get_context("fork")) as pool:
        subnets = list(pool.map(reserve, range(4)))
    assert len(set(subnets)) == 4
    host = networking.host_subnets()
    assert not any(s.overlaps(h) for s in subnets for h in host)


def test_reserved_subnets_of_exited_processes(reservations: Path) -> None:
    exited = subprocess.Popen(["true"])
    exited.wait()
    freed = ipaddress.IPv4Network("10.1.2.0/24")
    held = ipaddress.IPv4Network("10.1.3.0/24")
    networking.reservation(freed).write_text(str(exited.pid))
    networking.reservation(held).write_text(str(os.getpid()))
    assert networking.reserved_subnets() == [held]
    assert not networking.reservation(freed).exists()
