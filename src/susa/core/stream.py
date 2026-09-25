import time
from abc import ABC, abstractmethod


class Stream(ABC):
    @abstractmethod
    def read(self, size: int | None = None, timeout: float = 0) -> bytes:
        """Read up to `size` bytes (everything available if `size` is `None`), waiting up to `timeout` seconds for
        the first of them. Unlike a file's `read`, returns as soon as there's some data rather than waiting for
        `size` bytes, and returns `b""` if none arrives in time."""

    def read_until(self, expected: bytes, timeout: float) -> bytes:
        """Read until `expected` appears, returning everything read (which may go on after `expected`). Raises
        `TimeoutError` if it doesn't appear within `timeout` seconds."""
        deadline = time.time() + timeout
        result = b""
        while expected not in result:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise TimeoutError(
                    f"{expected!r} didn't appear within {timeout} seconds (got {result[-200:]!r})"
                )
            result += self.read(timeout=remaining)
        return result
