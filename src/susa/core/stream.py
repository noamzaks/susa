from __future__ import annotations

import time
from abc import ABC, abstractmethod

from typing_extensions import override


class OutputStream(ABC):
    @abstractmethod
    def read(self, size: int | None = None, timeout: float = 0) -> bytes: ...

    def read_until(self, expected: bytes, timeout: float) -> bytes:
        deadline = time.time() + timeout
        result = b""
        while expected not in result:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise TimeoutError(
                    f"{expected!r} didn't appear within {timeout} seconds (got {result!r})"
                )
            result += self.read(timeout=remaining)
        return result

    def read_all(self, timeout: float) -> bytes:
        deadline = time.time() + timeout
        result = b""
        while time.time() < deadline:
            try:
                result += self.read(timeout=deadline - time.time())
            except EOFError:
                return result
        raise TimeoutError(f"The stream didn't end within {timeout} seconds")

    def is_quiet(self, duration: float) -> bool:
        return self.read(timeout=duration) == b""

    def wait_until_quiet(self, quiet_time: float, timeout: float) -> None:
        deadline = time.time() + timeout
        while deadline - time.time() >= quiet_time:
            if self.is_quiet(quiet_time):
                return
        raise TimeoutError(
            f"Wasn't quiet for {quiet_time} seconds within {timeout} seconds"
        )


class SavedOutputStream(OutputStream):
    def __init__(self, stream: OutputStream):
        self.stream = stream
        self.data = b""

    @override
    def read(self, size: int | None = None, timeout: float = 0) -> bytes:
        result = self.stream.read(size=size, timeout=timeout)
        self.data += result
        return result


class InputStream(ABC):
    @abstractmethod
    def write(self, data: bytes) -> None: ...

    @abstractmethod
    def close(self) -> None: ...


class InputOutputStream(OutputStream, InputStream):
    pass
