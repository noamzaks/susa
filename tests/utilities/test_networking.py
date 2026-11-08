from __future__ import annotations

import fcntl
import ipaddress
import json
import multiprocessing
import os
import re
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pytest
from typing_extensions import override

from susa.core.communicator import HOST, HostAsyncCommandRunner
from susa.utilities.networking import (
    SubnetReservation,
    ping,
    pings,
    random_mac,
)


def test_ping() -> None:
    single = ping("127.0.0.1")
    assert isinstance(single, float)

    multiple = pings("127.0.0.1", 3, timeout=5, interval=1)
    assert len(multiple) == 3
    assert all(isinstance(time, float) for time in multiple)
    partial = pings("127.0.0.1", 5, timeout=2.5, interval=1)
    assert [time is not None for time in partial] == [True] * 3 + [False] * 2

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


def reserve() -> ipaddress.IPv4Network:
    reservation = SubnetReservation()
    reservation.create()
    assert reservation.subnet is not None
    return reservation.subnet


def locks(index: int) -> bool:
    lock = os.open(SubnetReservation.LOCK.get(), os.O_RDWR)
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
            assert subnet.subnet_of(reservation.subnets)
            used = reservation.host_subnets()
            assert not any(subnet.overlaps(other) for other in used)
            assert reservation.ip == str(subnet.network_address + 1)
            with SubnetReservation() as other:
                assert other.subnet != subnet
            subnets = {subnet, *(pool.submit(reserve).result() for _ in range(4))}
            assert len(subnets) == 5
            assert not pool.submit(locks, index).result()
        assert pool.submit(locks, index).result()


def test_subnet_reservation_lock(tmp_path: Path) -> None:
    with (
        SubnetReservation(lock=tmp_path / "a") as a,
        SubnetReservation(lock=tmp_path / "b") as b,
        SubnetReservation(lock=tmp_path / "a") as other,
    ):
        assert a.subnet == b.subnet != other.subnet
    with SubnetReservation.LOCK.set(str(tmp_path / "c")), SubnetReservation():
        assert (tmp_path / "c").exists()


def test_subnet_reservation_subnets(tmp_path: Path) -> None:
    lock = tmp_path / "lock"
    with SubnetReservation(Routes(), lock, "10.200.0.0/16") as wide:
        assert wide.subnet == ipaddress.IPv4Network("10.200.0.0/24")
        with pytest.raises(RuntimeError):
            SubnetReservation(Routes(), lock, "10.200.0.0/24").create()


def test_subnet_reservation_lock_environment(tmp_path: Path) -> None:
    lock = json.dumps(str(tmp_path / "lock"))
    environment = {**os.environ, "SUSA_SUBNETS_LOCK": lock}
    code = "from susa.utilities.networking import SubnetReservation as S; print(S.LOCK.get())"
    output = subprocess.check_output([sys.executable, "-c", code], env=environment)
    assert output.decode().strip() == str(tmp_path / "lock")


def test_subnet_reservation_closes_lock(tmp_path: Path) -> None:
    lock = tmp_path / "lock"
    with SubnetReservation(lock=lock), SubnetReservation(lock=lock):
        assert lock in SubnetReservation.FILES
    assert lock not in SubnetReservation.FILES


class Routes(HostAsyncCommandRunner):
    def __init__(self, *destinations: str) -> None:
        self.destinations = destinations

    @override
    def run(
        self, command: str, timeout: float | None = None
    ) -> subprocess.CompletedProcess[bytes]:
        routes = json.dumps([{"dst": destination} for destination in self.destinations])
        return subprocess.CompletedProcess(command, 0, routes.encode())


def test_subnet_reservation_host(tmp_path: Path) -> None:
    host = Routes("10.0.0.0/9", "default")
    first = ipaddress.IPv4Network("10.128.0.0/24")
    with SubnetReservation(host, tmp_path / "a") as reservation:
        assert reservation.subnet == first
    with HOST.set(host), SubnetReservation(lock=tmp_path / "b") as reservation:
        assert reservation.subnet == first
