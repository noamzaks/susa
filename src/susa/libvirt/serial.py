from __future__ import annotations

import libvirt as lv
from typing_extensions import override

from susa.core.machine import Serial
from susa.libvirt.stream import LVStream


class LVSerial(Serial):
    """A machine's first console, through libvirt (so it works even when the console's pty is only accessible to
    the QEMU user)."""

    def __init__(self, domain: lv.virDomain, conn: lv.virConnect) -> None:
        self.domain = domain
        self.conn = conn
        self.stream: LVStream | None = None

    @override
    def create(self) -> None:
        # `LVMachine.serial` returns created instances, which may then be used in a `with` block.
        if self.stream is not None:
            return

        stream = LVStream(self.conn)
        # No device name means the first console (or serial port). Take it over from anything else using it (e.g.
        # a `virsh console`).
        self.domain.openConsole(
            None,  # type: ignore[arg-type]
            stream.stream,
            lv.VIR_DOMAIN_CONSOLE_FORCE,
        )
        self.stream = stream

    @override
    def destroy(self) -> None:
        assert self.stream is not None
        self.stream.abort()
        self.stream = None

    @override
    def read(self, size: int | None = None, timeout: float = 0) -> bytes:
        assert self.stream is not None
        return self.stream.read(size, timeout)

    @override
    def write(self, data: bytes) -> None:
        assert self.stream is not None
        self.stream.write(data)
