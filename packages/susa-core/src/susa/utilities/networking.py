from __future__ import annotations

import fcntl
import ipaddress
import json
import os
import random
import re
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import ClassVar

from typing_extensions import override

from susa.core.communicator import HOST, AsyncCommandRunner, CommandRunner
from susa.core.resource import Resource
from susa.core.variable import EnvironmentVariable, Variable
from susa.utilities.generic import wait_until

PING_REPLY_PATTERN = re.compile(r"icmp_seq=(\d+)\b.*?\btime=([\d.]+) ms")


def ping(
    ip: str, timeout: float | None = 1, host: AsyncCommandRunner | None = None
) -> float | None:
    [time] = pings(ip, 1, timeout, host=host)
    return time


def pings(
    ip: str,
    count: int,
    timeout: float | None = 1,
    interval: float | None = None,
    host: AsyncCommandRunner | None = None,
) -> list[float | None]:
    command = ["ping", "-n", "-c", str(count)]
    if interval is not None:
        command += ["-i", str(interval)]
    command.append(ip)

    process = (host or HOST.get()).start(shlex.join(command))
    process.stdin.close()
    try:
        returncode = process.wait(timeout)
    except TimeoutError:
        process.kill()
        process.wait()
    else:
        # ping exits with 1 when some replies are missing, and with other codes on actual errors.
        if returncode not in (0, 1):
            raise subprocess.CalledProcessError(
                returncode, command, stderr=process.stderr.read_all()
            )
    output = process.stdout.read_all()

    times: list[float | None] = [None] * count
    for match in PING_REPLY_PATTERN.finditer(output.decode()):
        index = int(match.group(1)) - 1
        time = float(match.group(2))

        # Sanity.
        assert 0 <= index < count
        assert times[index] is None

        times[index] = time

    return times


def wait_until_ping(
    ip: str, timeout: float | None = None, host: AsyncCommandRunner | None = None
) -> None:
    wait_until(lambda: ping(ip, host=host) is not None, timeout)


def random_mac(prefix: str | None = None) -> str:
    parts = prefix.split(":") if prefix is not None else []
    parts += [f"{random.randrange(256):02x}" for _ in range(6 - len(parts))]
    return ":".join(parts)


# A /24 of the given subnets overlapping none of the host's routes, reserved across processes by locking its byte (its
# number among all /24s) of the lock file.
class SubnetReservation(Resource):
    LOCK: ClassVar[Variable[str]] = EnvironmentVariable(
        "SUSA_SUBNETS_LOCK",
        default_factory=lambda: str(Path(tempfile.gettempdir()) / "susa-subnets.lock"),
    )
    # A process' own locks don't stop it.
    TAKEN: ClassVar[set[tuple[Path, int]]] = set()
    # Open while this process has reservations in them, as closing any of its descriptors of one releases its locks.
    FILES: ClassVar[dict[Path, int]] = {}

    def __init__(
        self,
        host: CommandRunner | None = None,
        lock: str | Path | None = None,
        subnets: str = "10.0.0.0/8",
    ) -> None:
        self.host = host or HOST.get()
        self.lock = Path(lock or SubnetReservation.LOCK.get())
        self.subnets = ipaddress.IPv4Network(subnets)
        self.index: int | None = None
        self.subnet: ipaddress.IPv4Network | None = None

    @property
    def ip(self) -> str:
        assert self.subnet is not None
        return str(next(self.subnet.hosts()))

    @override
    def create(self) -> None:
        assert self.subnet is None
        used = self.host_subnets()
        lock = self.lock_file()
        for subnet in self.subnets.subnets(new_prefix=24):
            index = int(subnet.network_address) >> 8
            if (self.lock, index) in SubnetReservation.TAKEN or any(
                subnet.overlaps(other) for other in used
            ):
                continue
            try:
                fcntl.lockf(lock, fcntl.LOCK_EX | fcntl.LOCK_NB, 1, index)
            except OSError:
                continue
            SubnetReservation.TAKEN.add((self.lock, index))
            self.index, self.subnet = index, subnet
            return
        raise RuntimeError(f"There's no free subnet left in {self.subnets}")

    @override
    def destroy(self) -> None:
        assert self.index is not None and self.subnet is not None
        fcntl.lockf(SubnetReservation.FILES[self.lock], fcntl.LOCK_UN, 1, self.index)
        SubnetReservation.TAKEN.remove((self.lock, self.index))
        if not any(lock == self.lock for lock, _ in SubnetReservation.TAKEN):
            os.close(SubnetReservation.FILES.pop(self.lock))
        self.index, self.subnet = None, None

    # Every user locks it, which the umask stops at creation.
    def lock_file(self) -> int:
        if self.lock not in SubnetReservation.FILES:
            lock = SubnetReservation.FILES[self.lock] = os.open(
                self.lock, os.O_CREAT | os.O_RDWR, 0o666
            )
            if os.fstat(lock).st_uid == os.getuid():
                os.fchmod(lock, 0o666)
        return SubnetReservation.FILES[self.lock]

    def host_subnets(self) -> list[ipaddress.IPv4Network]:
        routes = json.loads(self.host.check("ip -json -4 route show table all"))
        return [
            ipaddress.IPv4Network(route["dst"], strict=False)
            for route in routes
            if route["dst"] != "default"
        ]
