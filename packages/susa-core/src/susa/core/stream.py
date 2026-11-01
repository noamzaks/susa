from __future__ import annotations

import io
import re
import select
from abc import ABC, abstractmethod
from concurrent.futures import Future, ThreadPoolExecutor
from typing import IO, Any, BinaryIO

from typing_extensions import override

from susa.utilities.generic import Deadline


class OutputStream(ABC):
    @abstractmethod
    def read(self, size: int | None = None, timeout: float | None = 0) -> bytes: ...

    def read_until(
        self, expected: bytes | re.Pattern[bytes], timeout: float | None = None
    ) -> bytes:
        deadline = Deadline(timeout)
        result = b""
        while not (
            expected in result
            if isinstance(expected, bytes)
            else expected.search(result)
        ):
            if deadline.passed():
                raise TimeoutError(
                    f"{expected!r} didn't appear within {timeout} seconds (got {result!r})"
                )
            result += self.read(timeout=deadline.remaining())
        return result

    def read_all(self, timeout: float | None = None) -> bytes:
        deadline = Deadline(timeout)
        result = b""
        while True:
            deadline.test("The stream didn't end")
            try:
                result += self.read(timeout=deadline.remaining())
            except EOFError:
                return result

    # In a thread, so that what writes it doesn't wait for it to be read (e.g. while it's waited for).
    def read_all_in_background(self) -> Future[bytes]:
        executor = ThreadPoolExecutor(1)
        future = executor.submit(self.read_all)
        executor.shutdown(wait=False)
        return future

    def file(self, timeout: float | None = None) -> BinaryIO:
        return io.BufferedReader(OutputStreamFile(self, timeout))

    def is_quiet(self, duration: float) -> bool:
        return self.read(timeout=duration) == b""

    def wait_until_quiet(self, quiet_time: float, timeout: float | None = None) -> None:
        deadline = Deadline(timeout)
        while (remaining := deadline.remaining()) is None or remaining >= quiet_time:
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
    def __init__(self, stream: OutputStream, timeout: float | None) -> None:
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
    def read(self, size: int | None = None, timeout: float | None = 0) -> bytes:
        result = self.stream.read(size=size, timeout=timeout)
        self.data += result
        return result


# An unbuffered file (whose reads return whatever arrived), e.g. a pipe.
class FileStream(InputOutputStream):
    CHUNK_SIZE = 1 << 16

    def __init__(self, handle: IO[bytes]) -> None:
        self.handle = handle

    @override
    def read(self, size: int | None = None, timeout: float | None = 0) -> bytes:
        if not select.select([self.handle], [], [], timeout)[0]:
            return b""
        data = self.handle.read(size or FileStream.CHUNK_SIZE)
        if not data:
            raise EOFError
        return data

    @override
    def write(self, data: bytes) -> None:
        while data:
            data = data[self.handle.write(data) :]

    @override
    def close(self) -> None:
        self.handle.close()
