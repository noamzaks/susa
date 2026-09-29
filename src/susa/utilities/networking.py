from __future__ import annotations

import random
import re
import subprocess
from typing import Literal, overload

from susa.utilities.generic import wait_until

PING_REPLY_PATTERN = re.compile(r"icmp_seq=(\d+)\b.*?\btime=([\d.]+) ms")


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

    if count == 1:
        return times[0]
    return times


def wait_until_ping(host: str, timeout: float) -> float:
    return wait_until(
        test=lambda timeout: ping(host, timeout=min(2, timeout)) is not None,
        timeout=timeout,
    )


def random_mac(prefix: str | None = None) -> str:
    parts = prefix.split(":") if prefix is not None else []
    parts += [f"{random.randrange(256):02x}" for _ in range(6 - len(parts))]
    return ":".join(parts)
