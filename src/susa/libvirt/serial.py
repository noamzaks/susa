from __future__ import annotations

import libvirt as lv
from typing_extensions import override

from susa.core.machine import Serial
from susa.libvirt.stream import LVStream


class LVSerial(Serial):
    def __init__(self, domain: lv.virDomain, conn: lv.virConnect) -> None:
        self.domain = domain
        self.conn = conn
        self.stream: LVStream | None = None

    @override
    def create(self) -> None:
        if self.stream is not None:
            return

        stream = LVStream(self.conn)
        self.domain.openConsole(
            None,  # type: ignore
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
    def close(self) -> None:
        self.destroy()

    @override
    def write(self, data: bytes) -> None:
        assert self.stream is not None
        self.stream.write(data)
