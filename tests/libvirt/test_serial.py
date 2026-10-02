from __future__ import annotations

from typing import cast

import pytest
from typing_extensions import override

from susa.libvirt.machine import LVMachine
from susa.libvirt.serial import LVConsole, LVSerial
from susa.libvirt.stream import LVStream


# A console that libvirt doesn't hand anything over to.
class FakeConsole(LVConsole):
    def __init__(self) -> None:
        super().__init__(cast(LVMachine, None))
        self.starts = 0

    @override
    def start(self) -> None:
        self.starts += 1
        self.stream = cast(LVStream, object())

    @override
    def end(self) -> None:
        self.stream = None
        self.receive(b"")


def test_serials_share_the_console() -> None:
    console = FakeConsole()
    with LVSerial(console) as first:
        console.receive(b"before ")
        with LVSerial(console) as second:
            console.receive(b"both")
            # Each gets what's said from when it's opened.
            assert first.read() == b"before both"
            assert second.read(2) == b"bo"
            assert second.read() == b"th"
        assert console.stream is not None
    assert console.starts == 1
    assert console.stream is None


def test_serial_end() -> None:
    console = FakeConsole()
    with LVSerial(console) as serial:
        console.receive(b"last")
        console.end()
        assert serial.read(timeout=1) == b"last"
        with pytest.raises(EOFError):
            serial.read(timeout=1)
        assert serial.read_available() == b""
        # Once ended, it stays ended.
        console.receive(b"more")
        assert serial.read_available() == b""
