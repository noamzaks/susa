from __future__ import annotations

import fcntl
import functools
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
PING_TIMEOUT = 2
# A byte per subnet, locked by the process that took it.
LOCK = Path(tempfile.gettempdir()) / "susa-subnets.lock"
# The subnets this process took (its own locks don't stop it).
TAKEN: set[ipaddress.IPv4Network] = set()


@overload
def ping(  # type: ignore
    host: str,
    count: Literal[1] = 1,
    timeout: float | None = 1,
    interval: float | None = None,
) -> float | None: ...


@overload
def ping(
    host: str,
    count: int,
    timeout: float | None = 1,
    interval: float | None = None,
) -> list[float | None]: ...


def ping(
    host: str, count: int = 1, timeout: float | None = 1, interval: float | None = None
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


def wait_until_ping(host: str, timeout: float | None = None) -> None:
    def answers(remaining: float | None) -> bool:
        attempt = PING_TIMEOUT if remaining is None else min(PING_TIMEOUT, remaining)
        return ping(host, timeout=attempt) is not None

    wait_until(answers, timeout)


def random_mac(prefix: str | None = None) -> str:
    parts = prefix.split(":") if prefix is not None else []
    parts += [f"{random.randrange(256):02x}" for _ in range(6 - len(parts))]
    return ":".join(parts)


# The first /24 overlapping none of the host's routes (e.g. its networks) that no process took. It's taken (its byte of
# `LOCK` stays locked) until this process exits.
def free_subnet() -> ipaddress.IPv4Network:
    used = host_subnets()
    lock = lock_file()
    for index, subnet in enumerate(SUBNETS.subnets(new_prefix=24)):
        if subnet in TAKEN or any(subnet.overlaps(other) for other in used):
            continue
        try:
            fcntl.lockf(lock, fcntl.LOCK_EX | fcntl.LOCK_NB, 1, index)
        except OSError:
            continue
        TAKEN.add(subnet)
        return subnet
    raise RuntimeError(f"There's no free subnet left in {SUBNETS}")


# Open while this process runs, as closing any of its descriptors releases the process' locks.
@functools.cache
def lock_file() -> int:
    return os.open(LOCK, os.O_CREAT | os.O_RDWR)


def host_subnets() -> list[ipaddress.IPv4Network]:
    routes = json.loads(
        subprocess.check_output(["ip", "-json", "-4", "route", "show", "table", "all"])
    )
    return [
        ipaddress.IPv4Network(route["dst"], strict=False)
        for route in routes
        if route["dst"] != "default"
    ]
