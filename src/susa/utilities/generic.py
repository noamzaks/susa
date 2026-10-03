from __future__ import annotations

import random
import string
import time
from collections.abc import Callable

GIGA = 1 << 30


def random_id(length: int) -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


# `timeout` seconds from now, or never if it's `None`.
class Deadline:
    def __init__(self, timeout: float | None) -> None:
        self.timeout = timeout
        self.end = None if timeout is None else time.monotonic() + timeout

    # What's left of the timeout (`None` if there's none).
    def remaining(self) -> float | None:
        return None if self.end is None else max(0.0, self.end - time.monotonic())

    def passed(self) -> bool:
        return self.remaining() == 0


def wait_until(
    test: Callable[[float | None], bool],
    timeout: float | None = None,
    interval: float = 0.1,
) -> None:
    deadline = Deadline(timeout)
    while not deadline.passed():
        if test(deadline.remaining()):
            return
        time.sleep(interval)
    raise TimeoutError(f"Timed out after {timeout} seconds")
