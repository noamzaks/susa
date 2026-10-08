from __future__ import annotations

import pexpect
from typing_extensions import override

from susa.core.stream import InputOutputStream


class ProcessStream(InputOutputStream):
    def __init__(self, *argv: str, env: dict[str, str] | None = None) -> None:
        self.process: pexpect.spawn[bytes] = pexpect.spawn(
            argv[0], list(argv[1:]), env=env
        )

    @override
    def read(self, size: int | None = None, timeout: float | None = 0) -> bytes:
        try:
            return self.process.read_nonblocking(size or self.process.maxread, timeout)
        except pexpect.TIMEOUT:
            return b""
        except pexpect.EOF:
            raise EOFError from None

    @override
    def write(self, data: bytes) -> None:
        self.process.send(data)

    @override
    def close(self) -> None:
        self.process.close()
