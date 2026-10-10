from __future__ import annotations

import fcntl
import ipaddress
import multiprocessing
import os
import re
import subprocess
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pytest

from susa.utilities.networking import (
    SubnetReservation,
    ping,
    pings,
    random_mac,
)


def test_ping() -> None:
    single = ping("127.0.0.1")
    assert isinstance(single, float)

    # The timeout is for the whole run.
    multiple = pings("127.0.0.1", 3, timeout=5, interval=1)
    assert len(multiple) == 3
    assert all(isinstance(time, float) for time in multiple)

    # 10.255.255.1 is a non-routable address, so no replies should come back.
    assert pings("10.255.255.1", 2) == [None, None]

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


# Kept until the worker exits.
def reserve() -> ipaddress.IPv4Network:
    reservation = SubnetReservation()
    reservation.create()
    assert reservation.subnet is not None
    return reservation.subnet


def locks(index: int) -> bool:
    lock = os.open(SubnetReservation.LOCK, os.O_RDWR)
    try:
        fcntl.lockf(lock, fcntl.LOCK_EX | fcntl.LOCK_NB, 1, index)
    except OSError:
        return False
    return True


def test_subnet_reservation() -> None:
    with ProcessPoolExecutor(4, multiprocessing.get_context("spawn")) as pool:
        with SubnetReservation() as reservation:
            subnet, index = reservation.subnet, reservation.index
            assert subnet is not None and index is not None
            assert subnet.prefixlen == 24
            assert subnet.subnet_of(SubnetReservation.SUBNETS)
            used = reservation.host_subnets()
            assert not any(subnet.overlaps(other) for other in used)
            assert reservation.address == str(subnet.network_address + 1)
            with SubnetReservation() as other:
                assert other.subnet != subnet
            subnets = {subnet, *(pool.submit(reserve).result() for _ in range(4))}
            assert len(subnets) == 5
            assert not pool.submit(locks, index).result()
        assert pool.submit(locks, index).result()


def test_subnet_reservation_lock(tmp_path: Path) -> None:
    with (
        SubnetReservation(tmp_path / "a") as a,
        SubnetReservation(tmp_path / "b") as b,
        SubnetReservation(tmp_path / "a") as other,
    ):
        assert a.subnet == b.subnet != other.subnet


def test_subnet_reservation_lock_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(SubnetReservation.LOCK_VARIABLE, str(tmp_path / "lock"))
    with SubnetReservation():
        assert (tmp_path / "lock").exists()


def test_subnet_reservation_closes_lock(tmp_path: Path) -> None:
    lock = tmp_path / "lock"
    with SubnetReservation(lock), SubnetReservation(lock):
        assert lock in SubnetReservation.FILES
    assert lock not in SubnetReservation.FILES
