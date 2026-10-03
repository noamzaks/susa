from __future__ import annotations

import random
import string
import time
from collections.abc import Callable

GIGA = 1 << 30


def random_id(length: int) -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


def wait_until(
    test: Callable[[float], bool], timeout: float, interval: float = 0.1
) -> None:
    deadline = time.monotonic() + timeout
    while (remaining := deadline - time.monotonic()) > 0:
        if test(remaining):
            return
        time.sleep(min(interval, remaining))
    raise TimeoutError(f"Timed out after {timeout} seconds")
