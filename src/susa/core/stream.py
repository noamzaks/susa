from __future__ import annotations

import io
import time
from abc import ABC, abstractmethod
from typing import Any, BinaryIO

from pexpect.spawnbase import SpawnBase
from typing_extensions import override


class OutputStream(ABC):
    @abstractmethod
    def read(self, size: int | None = None, timeout: float = 0) -> bytes: ...

    def read_until(self, expected: bytes, timeout: float) -> bytes:
        deadline = time.monotonic() + timeout
        result = b""
        while expected not in result:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"{expected!r} didn't appear within {timeout} seconds (got {result!r})"
                )
            result += self.read(timeout=remaining)
        return result

    def read_all(self, timeout: float) -> bytes:
        deadline = time.monotonic() + timeout
        result = b""
        while (remaining := deadline - time.monotonic()) > 0:
            try:
                result += self.read(timeout=remaining)
            except EOFError:
                return result
        raise TimeoutError(f"The stream didn't end within {timeout} seconds")

    def file(self, timeout: float) -> BinaryIO:
        return io.BufferedReader(OutputStreamFile(self, timeout))

    def is_quiet(self, duration: float) -> bool:
        return self.read(timeout=duration) == b""

    def wait_until_quiet(self, quiet_time: float, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while deadline - time.monotonic() >= quiet_time:
            if self.is_quiet(quiet_time):
                return
        raise TimeoutError(
            f"Wasn't quiet for {quiet_time} seconds within {timeout} seconds"
        )


class InputStream(ABC):
    @abstractmethod
    def write(self, data: bytes) -> None: ...

    @abstractmethod
    def close(self) -> None: ...


class InputOutputStream(OutputStream, InputStream):
    pass


class OutputStreamFile(io.RawIOBase):
    def __init__(self, stream: OutputStream, timeout: float) -> None:
        self.stream = stream
        self.timeout = timeout

    @override
    def readable(self) -> bool:
        return True

    @override
    def readinto(self, buffer: Any) -> int:
        try:
            data = self.stream.read(len(buffer), self.timeout)
        except EOFError:
            return 0
        if not data:
            raise TimeoutError(f"No data arrived within {self.timeout} seconds")
        buffer[: len(data)] = data
        return len(data)


class SavedOutputStream(OutputStream):
    def __init__(self, stream: OutputStream):
        self.stream = stream
        self.data = b""

    @override
    def read(self, size: int | None = None, timeout: float = 0) -> bytes:
        result = self.stream.read(size=size, timeout=timeout)
        self.data += result
        return result


# pexpect's `expect` over a stream.
class PexpectStream(SpawnBase):  # type: ignore
    def __init__(self, stream: OutputStream) -> None:
        super().__init__()
        self.stream = stream

    @override
    def read_nonblocking(self, size: int = 1, timeout: float | None = None) -> bytes:
        # Sanity.
        assert timeout is not None
        return self.stream.read(size, timeout)
