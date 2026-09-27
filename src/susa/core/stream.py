from __future__ import annotations

import time
from abc import ABC, abstractmethod


class OutputStream(ABC):
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

    def is_quiet(self, duration: float) -> bool:
        """Whether nothing arrives within `duration` seconds (discarding whatever does)."""
        return self.read(timeout=duration) == b""

    def wait_until_quiet(self, quiet_time: float, timeout: float) -> None:
        """Discard data until none arrives for `quiet_time` seconds. Raises `TimeoutError` if that doesn't happen
        within `timeout` seconds (a quiet period that wouldn't fit in it isn't started)."""
        deadline = time.time() + timeout
        while deadline - time.time() >= quiet_time:
            if self.is_quiet(quiet_time):
                return
        raise TimeoutError(
            f"Wasn't quiet for {quiet_time} seconds within {timeout} seconds"
        )


class InputStream(ABC):
    @abstractmethod
    def write(self, data: bytes) -> None: ...


class InputOutputStream(OutputStream, InputStream):
    pass
