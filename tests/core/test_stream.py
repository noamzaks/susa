from __future__ import annotations

import pytest
from typing_extensions import override

from susa.core.stream import OutputStream


class FakeStream(OutputStream):
    def __init__(self, *chunks: bytes) -> None:
        self.chunks = list(chunks)

    @override
    def read(self, size: int | None = None, timeout: float = 0) -> bytes:
        return self.chunks.pop(0) if self.chunks else b""


def test_read_until() -> None:
    stream = FakeStream(b"booting\r\n", b"susa lo", b"gin: ", b"after")
    assert stream.read_until(b"login:", timeout=1) == b"booting\r\nsusa login: "
    assert stream.read() == b"after"


def test_read_until_timeout() -> None:
    with pytest.raises(TimeoutError, match="login"):
        FakeStream(b"booting\r\n").read_until(b"login:", timeout=0.1)
