from __future__ import annotations

import re
import time

import pytest
from typing_extensions import override

from susa.core.stream import OutputStream, PexpectStream


class FakeStream(OutputStream):
    def __init__(self, *chunks: bytes) -> None:
        self.chunks = list(chunks)

    @override
    def read(self, size: int | None = None, timeout: float | None = 0) -> bytes:
        return self.chunks.pop(0) if self.chunks else b""


def test_read_until() -> None:
    stream = FakeStream(b"booting\r\n", b"susa lo", b"gin: ", b"after")
    assert stream.read_until(b"login:", timeout=1) == b"booting\r\nsusa login: "
    assert stream.read() == b"after"


def test_read_until_timeout() -> None:
    with pytest.raises(TimeoutError, match="login"):
        FakeStream(b"booting\r\n").read_until(b"login:", timeout=0.1)


class SlowStream(OutputStream):
    # Data every `interval` seconds, forever.

    def __init__(self, interval: float) -> None:
        self.interval = interval

    @override
    def read(self, size: int | None = None, timeout: float | None = 0) -> bytes:
        if timeout is not None and timeout < self.interval:
            time.sleep(timeout)
            return b""
        time.sleep(self.interval)
        return b"x"


def test_wait_until_quiet() -> None:
    FakeStream(b"a", b"b").wait_until_quiet(0.1, timeout=1)
    start = time.time()
    with pytest.raises(TimeoutError):
        SlowStream(0.05).wait_until_quiet(0.3, timeout=1)
    # It doesn't start a quiet period that wouldn't fit before the timeout.
    assert time.time() - start < 1


def test_expect() -> None:
    stream = PexpectStream(FakeStream(b"booting\r\nsusa lo", b"gin: after"))
    assert stream.expect([rb"login: ", rb"Password: "], timeout=1) == 0
    assert stream.before == b"booting\r\nsusa "
    assert stream.expect(rb"af(t)er", timeout=1) == 0
    assert isinstance(stream.match, re.Match)
    assert stream.match.group(1) == b"t"
