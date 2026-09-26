from __future__ import annotations

import time
from typing import Any, Protocol

import pexpect
from pexpect.spawnbase import SpawnBase
from typing_extensions import override

from susa.core.stream import InputOutputStream


class Terminal(Protocol):
    """A pexpect-style (bytes) connection to something that reads lines, like a shell or a login prompt."""

    before: bytes | None
    match: Any

    def expect(self, pattern: Any, timeout: float | None = -1) -> int: ...

    def send(self, s: bytes) -> int: ...

    def sendline(self, s: bytes = b"") -> int: ...

    def sendintr(self) -> None: ...

    def close(self) -> None: ...

    def is_quiet(self, duration: float) -> bool: ...

    def wait_until_quiet(self, quiet_time: float, timeout: float = 60) -> None: ...


class QuietSpawn(SpawnBase):  # type: ignore[type-arg]
    def is_quiet(self, duration: float) -> bool:
        """Whether nothing arrives within `duration` seconds (discarding whatever does)."""
        return self.expect([rb"[\s\S]+", pexpect.TIMEOUT], duration) == 1

    def wait_until_quiet(self, quiet_time: float, timeout: float = 60) -> None:
        deadline = time.time() + timeout
        while not self.is_quiet(quiet_time):
            if time.time() > deadline:
                raise TimeoutError(f"The terminal wasn't quiet for {timeout} seconds")


class ProcessTerminal(QuietSpawn, pexpect.spawn):  # type: ignore[type-arg]
    """A local process (in a pty)."""

    def __init__(self, *argv: str) -> None:
        super().__init__(argv[0], list(argv[1:]))


class StreamTerminal(QuietSpawn):
    """A terminal over `stream` (e.g. a serial console)."""

    def __init__(self, stream: InputOutputStream, timeout: float = 30) -> None:
        super().__init__(timeout=timeout)
        self.stream = stream

    @override
    def read_nonblocking(self, size: int = 1, timeout: float | None = None) -> bytes:
        if timeout is None or timeout == -1:
            timeout = self.timeout or 0
        return self.stream.read(size, timeout)

    def send(self, s: bytes) -> int:
        self.stream.write(s)
        return len(s)

    def sendline(self, s: bytes = b"") -> int:
        return self.send(s + b"\r")

    def sendintr(self) -> None:
        self.send(b"\x03")

    def close(self) -> None:
        pass
