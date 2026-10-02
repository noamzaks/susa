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
from typing import Literal, overload

from susa.utilities.generic import wait_until

PING_REPLY_PATTERN = re.compile(r"icmp_seq=(\d+)\b.*?\btime=([\d.]+) ms")
SUBNETS = ipaddress.IPv4Network("10.0.0.0/8")
# A file per reserved subnet, holding the reserving process' ID.
RESERVATIONS = Path(tempfile.gettempdir()) / "susa-subnets"


@overload
def ping(  # type: ignore
    host: str,
    count: Literal[1] = 1,
    timeout: float | None = 1,
    interval: int | None = None,
) -> float | None: ...


@overload
def ping(
    host: str,
    count: int,
    timeout: float | None = 1,
    interval: int | None = None,
) -> list[float | None]: ...


def ping(
    host: str, count: int = 1, timeout: float | None = 1, interval: int | None = None
) -> list[float | None] | float | None:
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

    return times[0] if count == 1 else times


def wait_until_ping(host: str, timeout: float) -> float:
    return wait_until(
        test=lambda timeout: ping(host, timeout=min(2, timeout)) is not None,
        timeout=timeout,
    )


def random_mac(prefix: str | None = None) -> str:
    parts = prefix.split(":") if prefix is not None else []
    parts += [f"{random.randrange(256):02x}" for _ in range(6 - len(parts))]
    return ":".join(parts)


# A subnet that's free (overlapping none of the host's routes, e.g. its networks), reserved for this process (until it
# exits), so other processes (each holding the lock while reserving) don't reserve it too.
def reserve_subnet(prefix: int = 24) -> ipaddress.IPv4Network:
    RESERVATIONS.mkdir(exist_ok=True)
    with open(RESERVATIONS / "lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        used = host_subnets() + reserved_subnets()
        subnet = next(
            subnet
            for subnet in SUBNETS.subnets(new_prefix=prefix)
            if not any(subnet.overlaps(other) for other in used)
        )
        reservation(subnet).write_text(str(os.getpid()))
    return subnet


def host_subnets() -> list[ipaddress.IPv4Network]:
    routes = json.loads(
        subprocess.run(
            ["ip", "-json", "-4", "route", "show", "table", "all"],
            capture_output=True,
            check=True,
        ).stdout
    )
    return [
        ipaddress.IPv4Network(route["dst"], strict=False)
        for route in routes
        if route["dst"] != "default"
    ]


# Reservations of processes that exited are removed.
def reserved_subnets() -> list[ipaddress.IPv4Network]:
    result = []
    for path in RESERVATIONS.glob("*_*"):
        if alive(int(path.read_text())):
            result.append(ipaddress.IPv4Network(path.name.replace("_", "/")))
        else:
            path.unlink()
    return result


def reservation(subnet: ipaddress.IPv4Network) -> Path:
    return RESERVATIONS / str(subnet).replace("/", "_")


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Another user's.
        pass
    return True
