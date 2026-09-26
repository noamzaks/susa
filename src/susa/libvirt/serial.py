from __future__ import annotations

import time

import libvirt as lv
from typing_extensions import override

from susa.core.machine import Serial

POLL_INTERVAL = 0.05
# How much to ask the stream for at a time when reading everything available.
CHUNK_SIZE = 1 << 16


class LVSerial(Serial):
    """A machine's first console, through libvirt (so it works even when the console's pty is only accessible to
    the QEMU user). Needs libvirt's event loop, which `Connection` starts."""

    def __init__(self, domain: lv.virDomain, conn: lv.virConnect) -> None:
        self.domain = domain
        self.conn = conn
        self.stream: lv.virStream | None = None

    @override
    def create(self) -> None:
        # `LVMachine.serial` returns created instances, which may then be used in a `with` block.
        if self.stream is not None:
            return

        stream = self.conn.newStream(lv.VIR_STREAM_NONBLOCK)
        # No device name means the first console (or serial port). Take it over from anything else using it (e.g.
        # a `virsh console`).
        self.domain.openConsole(
            None,  # type: ignore[arg-type]
            stream,
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
        deadline = time.time() + timeout
        result = b""
        while size is None or len(result) < size:
            # Returns -2 (despite its annotation) when a non-blocking stream has no data right now.
            data: bytes | int = self.stream.recv(
                CHUNK_SIZE if size is None else size - len(result)
            )
            if isinstance(data, int):
                remaining = deadline - time.time()
                if result or remaining <= 0:
                    break
                time.sleep(min(POLL_INTERVAL, remaining))
                continue
            if not data:
                # The console was closed.
                break
            result += data
        return result

    @override
    def write(self, data: bytes) -> None:
        assert self.stream is not None
        while data:
            sent = self.stream.send(data)
            if sent == -2:
                time.sleep(POLL_INTERVAL)
                continue
            data = data[sent:]
