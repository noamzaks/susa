from __future__ import annotations

import time

import libvirt as lv
from typing_extensions import override

from susa.core.stream import InputOutputStream

POLL_INTERVAL = 0.05
# How much to ask for at a time when reading everything available.
CHUNK_SIZE = 1 << 16


class LVStream(InputOutputStream):
    def __init__(self, conn: lv.virConnect) -> None:
        self.stream = conn.newStream(lv.VIR_STREAM_NONBLOCK)
        self.eof = False

    @override
    def read(self, size: int | None = None, timeout: float = 0) -> bytes:
        deadline = time.time() + timeout
        result = b""
        while not self.eof and (size is None or len(result) < size):
            # Returns -2 (despite its annotation) when there's no data right now.
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
                self.eof = True
            result += data
        if self.eof and not result:
            raise EOFError
        return result

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

    def abort(self) -> None:
        self.stream.abort()
