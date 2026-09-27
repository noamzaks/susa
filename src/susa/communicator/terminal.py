from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol

import pexpect
from pexpect.spawnbase import SpawnBase
from typing_extensions import override

from susa.core.stream import InputOutputStream


class Terminal(Protocol):
    """A pexpect-style (bytes) connection to something that reads lines, like a shell or a login prompt. It's also
    an `InputOutputStream` (e.g. to wait until it's quiet)."""

    before: bytes | None
    match: Any

    def expect(self, pattern: Any, timeout: float | None = -1) -> int: ...

    def send(self, s: str | bytes) -> int: ...

    def sendline(self, s: str | bytes = b"") -> int: ...

    def sendintr(self) -> None: ...

    def close(self) -> None: ...

    def read(self, size: int | None = None, timeout: float = 0) -> bytes: ...

    def is_quiet(self, duration: float) -> bool: ...

    def wait_until_quiet(self, quiet_time: float, timeout: float) -> None: ...


class TerminalStream(SpawnBase, InputOutputStream):  # type: ignore[type-arg]
    """A pexpect spawn as an `InputOutputStream`."""

    if TYPE_CHECKING:
        # Provided by pexpect's `spawn`, or by subclasses.
        def send(self, s: str | bytes) -> int: ...

    @override
    def read(self, size: int | None = None, timeout: float = 0) -> bytes:
        # Data `expect` read past its match comes first.
        buffered: bytes = self.buffer
        if buffered:
            data = buffered if size is None else buffered[:size]
            self.buffer = buffered[len(data) :]
            return data
        try:
            result: bytes = self.read_nonblocking(size or self.maxread, timeout)
            return result
        except (pexpect.TIMEOUT, pexpect.EOF):
            return b""

    @override
    def write(self, data: bytes) -> None:
        self.send(data)


class ProcessTerminal(TerminalStream, pexpect.spawn):  # type: ignore[type-arg,misc]
    """A local process (in a pty)."""

    def __init__(self, *argv: str, env: dict[str, str] | None = None) -> None:
        super().__init__(argv[0], list(argv[1:]), env=env)
        # Lines end like a terminal's Enter key does, which is what programs reading raw input expect.
        self.linesep = b"\r"


class StreamTerminal(TerminalStream):
    """A terminal over `stream` (e.g. a serial console or a socket). `close` is called when it's closed."""

    def __init__(
        self,
        stream: InputOutputStream,
        close: Callable[[], None] | None = None,
        timeout: float = 30,
    ) -> None:
        super().__init__(timeout=timeout)
        self.stream = stream
        self.on_close = close

    @override
    def read_nonblocking(self, size: int = 1, timeout: float | None = None) -> bytes:
        if timeout is None or timeout == -1:
            timeout = self.timeout or 0
        return self.stream.read(size, timeout)

    @override
    def send(self, s: str | bytes) -> int:
        data = s.encode() if isinstance(s, str) else s
        self.stream.write(data)
        return len(data)

    def sendline(self, s: str | bytes = b"") -> int:
        return self.send((s.encode() if isinstance(s, str) else s) + b"\r")

    def sendintr(self) -> None:
        self.send(b"\x03")

    def close(self) -> None:
        if self.on_close is not None:
            self.on_close()
