from __future__ import annotations

import random
import string
import time
from collections.abc import Callable

KILO = 1 << 10
MEGA = KILO << 10
GIGA = MEGA << 10


def random_id(length: int) -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


def wait_until(test: Callable[[float], bool], timeout: float) -> float:
    start = time.time()

    while (remaining := start + timeout - time.time()) > 0:
        if test(remaining):
            return time.time() - start

    raise TimeoutError(f"timed out after {timeout} seconds")
