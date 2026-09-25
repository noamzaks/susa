import platform
import random
import string
import time
from collections.abc import Callable

KILO = 1 << 10
MEGA = KILO << 10
GIGA = MEGA << 10


def random_id(length: int) -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


def host_arch() -> str:
    machine = platform.machine()
    if machine in ("aarch64", "arm64"):
        return "aarch64"
    if machine in ("x86_64", "amd64", "AMD64"):
        return "x86_64"
    raise ValueError(f"Unknown host architecture: {machine!r}")


def try_wait_for(test: Callable[[], bool], attempts: int | None = None) -> int | None:
    attempt = 0

    while attempts is None or attempt < attempts:
        attempt += 1
        if test():
            return attempt

    return None


def wait_for(test: Callable[[], bool], attempts: int | None = None) -> int:
    result = try_wait_for(test=test, attempts=attempts)
    assert result is not None

    return result


def wait_until(test: Callable[[float], bool], timeout: float) -> float:
    """
    Call `test` with the remaining time until it returns `True`, returning how many seconds that took. Raises
    `TimeoutError` if `timeout` seconds pass first.
    """
    start = time.time()

    while (remaining := start + timeout - time.time()) > 0:
        if test(remaining):
            return time.time() - start

    raise TimeoutError(f"timed out after {timeout} seconds")
