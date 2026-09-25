import math
import random
import re
import subprocess
import time
from typing import Literal, overload

from susa.utilities.generic import wait_until

PING_REPLY_PATTERN = re.compile(r"icmp_seq=(\d+)\b.*?\btime=([\d.]+) ms")


@overload
def ping(  # type: ignore[overload-overlap]
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
    """
    Ping `host` `count` times, returning the round-trip time of each ping in milliseconds (or `None` if no reply
    came back). If `count` is 1, the single result is returned directly instead of a list.

    `timeout` is how many seconds to wait for each reply (`None` waits forever), and `interval` is how many seconds
    to wait between pings (1 by default).
    """
    command = ["ping", "-n", "-c", str(count)]
    if timeout is not None:
        # ping only has a deadline for the whole run, so give the last ping `timeout` seconds after it's sent.
        deadline = (count - 1) * (interval if interval is not None else 1) + timeout
        command += ["-w", str(math.ceil(deadline))]
    if interval is not None:
        command += ["-i", str(interval)]
    command.append(host)

    result = subprocess.run(command, capture_output=True, text=True, check=False)
    # ping exits with 1 when some replies are missing, and with other codes on actual errors.
    if result.returncode not in (0, 1):
        raise subprocess.CalledProcessError(
            result.returncode, command, result.stdout, result.stderr
        )

    times: list[float | None] = [None] * count
    for match in PING_REPLY_PATTERN.finditer(result.stdout):
        index = int(match.group(1)) - 1
        # Ignore out-of-range sequence numbers and duplicate replies.
        if 0 <= index < count and times[index] is None:
            times[index] = float(match.group(2))

    if count == 1:
        return times[0]
    return times


def wait_until_ping(host: str, timeout: float) -> float:
    """
    Wait until `host` replies to a ping, returning how many seconds that took. Raises `TimeoutError` if it doesn't
    within `timeout` seconds.
    """

    def test(remaining: float) -> bool:
        if ping(host, timeout=max(1, remaining)) is not None:
            return True
        # ping gives up early on errors (e.g. the host is unreachable while it boots), so don't spin.
        time.sleep(min(1, remaining))
        return False

    return wait_until(test=test, timeout=timeout)


def random_mac(prefix: str | None = None) -> str:
    parts = prefix.split(":") if prefix is not None else []
    parts += [f"{random.randrange(256):02x}" for _ in range(6 - len(parts))]
    return ":".join(parts)
