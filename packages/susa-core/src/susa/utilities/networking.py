from __future__ import annotations

import fcntl
import ipaddress
import json
import os
import random
import re
import subprocess
import tempfile
from pathlib import Path
from typing import ClassVar

from typing_extensions import override

from susa.core.resource import Resource
from susa.utilities.generic import wait_until

PING_REPLY_PATTERN = re.compile(r"icmp_seq=(\d+)\b.*?\btime=([\d.]+) ms")


def ping(host: str, timeout: float | None = 1) -> float | None:
    [time] = pings(host, 1, timeout)
    return time


def pings(
    host: str, count: int, timeout: float | None = 1, interval: float | None = None
) -> list[float | None]:
    command = ["ping", "-n", "-c", str(count)]
    if interval is not None:
        command += ["-i", str(interval)]
    command.append(host)

    try:
        result = subprocess.run(
            command, capture_output=True, check=False, timeout=timeout
        )
    except subprocess.TimeoutExpired as e:
        output = e.stdout or b""
    else:
        # ping exits with 1 when some replies are missing, and with other codes on actual errors.
        if result.returncode not in (0, 1):
            raise subprocess.CalledProcessError(
                result.returncode, command, result.stdout, result.stderr
            )
        output = result.stdout

    times: list[float | None] = [None] * count
    for match in PING_REPLY_PATTERN.finditer(output.decode()):
        index = int(match.group(1)) - 1
        time = float(match.group(2))

        # Sanity.
        assert 0 <= index < count
        assert times[index] is None

        times[index] = time

    return times


def wait_until_ping(host: str, timeout: float | None = None) -> None:
    wait_until(lambda: ping(host) is not None, timeout)


def random_mac(prefix: str | None = None) -> str:
    parts = prefix.split(":") if prefix is not None else []
    parts += [f"{random.randrange(256):02x}" for _ in range(6 - len(parts))]
    return ":".join(parts)


# A /24 overlapping none of the host's routes, reserved across processes by locking its byte of the lock file.
class SubnetReservation(Resource):
    SUBNETS = ipaddress.IPv4Network("10.0.0.0/8")
    LOCK = Path(tempfile.gettempdir()) / "susa-subnets.lock"
    LOCK_VARIABLE = "SUSA_SUBNETS_LOCK"
    # A process' own locks don't stop it.
    TAKEN: ClassVar[set[tuple[Path, int]]] = set()
    # Open while this process has reservations in them, as closing any of its descriptors of one releases its locks.
    FILES: ClassVar[dict[Path, int]] = {}

    def __init__(self, lock: str | Path | None = None) -> None:
        self.lock = Path(lock or os.environ.get(self.LOCK_VARIABLE) or self.LOCK)
        self.index: int | None = None
        self.subnet: ipaddress.IPv4Network | None = None

    @property
    def address(self) -> str:
        assert self.subnet is not None
        return str(next(self.subnet.hosts()))

    @override
    def create(self) -> None:
        assert self.subnet is None
        used = self.host_subnets()
        lock = self.lock_file()
        for index, subnet in enumerate(self.SUBNETS.subnets(new_prefix=24)):
            if (self.lock, index) in self.TAKEN or any(
                subnet.overlaps(other) for other in used
            ):
                continue
            try:
                fcntl.lockf(lock, fcntl.LOCK_EX | fcntl.LOCK_NB, 1, index)
            except OSError:
                continue
            self.TAKEN.add((self.lock, index))
            self.index, self.subnet = index, subnet
            return
        raise RuntimeError(f"There's no free subnet left in {self.SUBNETS}")

    @override
    def destroy(self) -> None:
        assert self.index is not None and self.subnet is not None
        fcntl.lockf(self.FILES[self.lock], fcntl.LOCK_UN, 1, self.index)
        self.TAKEN.remove((self.lock, self.index))
        if not any(lock == self.lock for lock, _ in self.TAKEN):
            os.close(self.FILES.pop(self.lock))
        self.index, self.subnet = None, None

    # Every user locks it, which the umask stops at creation.
    def lock_file(self) -> int:
        if self.lock not in self.FILES:
            lock = self.FILES[self.lock] = os.open(
                self.lock, os.O_CREAT | os.O_RDWR, 0o666
            )
            if os.fstat(lock).st_uid == os.getuid():
                os.fchmod(lock, 0o666)
        return self.FILES[self.lock]

    @staticmethod
    def host_subnets() -> list[ipaddress.IPv4Network]:
        command = ["ip", "-json", "-4", "route", "show", "table", "all"]
        routes = json.loads(subprocess.check_output(command))
        return [
            ipaddress.IPv4Network(route["dst"], strict=False)
            for route in routes
            if route["dst"] != "default"
        ]
