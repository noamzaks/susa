from __future__ import annotations

import time

import libvirt as lv
from typing_extensions import override

from susa.core.stream import InputOutputStream
from susa.utilities.generic import Deadline

POLL_INTERVAL = 0.05
CHUNK_SIZE = 1 << 16


# A non-blocking libvirt stream, polled.
class LVStream(InputOutputStream):
    def __init__(self, conn: lv.virConnect) -> None:
        self.stream = conn.newStream(lv.VIR_STREAM_NONBLOCK)
        # libvirt fails reads after the end.
        self.eof = False

    @override
    def read(self, size: int | None = None, timeout: float | None = 0) -> bytes:
        deadline = Deadline(timeout)
        while not self.eof:
            # -2 (despite its annotation) when there's nothing to read yet.
            data: bytes | int = self.stream.recv(size or CHUNK_SIZE)
            if isinstance(data, bytes):
                self.eof = not data
                if data:
                    return data
            elif deadline.passed():
                return b""
            else:
                time.sleep(POLL_INTERVAL)
        raise EOFError

    @override
    def write(self, data: bytes) -> None:
        while data:
            sent = self.stream.send(data)
            if sent == -2:
                time.sleep(POLL_INTERVAL)
                continue
            data = data[sent:]

    @override
    def close(self) -> None:
        self.stream.finish()
