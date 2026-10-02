from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Any

import libvirt as lv
from typing_extensions import override

from susa.core.machine import Serial
from susa.libvirt.stream import CHUNK_SIZE, LVStream

if TYPE_CHECKING:
    from susa.libvirt.machine import LVMachine


# A machine's (first) console, open while it has serials, each getting everything it says from when it's opened. It's
# handed over by libvirt's event loop (see `Connection`), from another thread.
class LVConsole:
    def __init__(self, machine: LVMachine) -> None:
        self.machine = machine
        self.stream: LVStream | None = None
        self.serials: list[LVSerial] = []
        self.lock = threading.Lock()

    def open(self, serial: LVSerial) -> None:
        with self.lock:
            # Sanity.
            assert serial not in self.serials
            if self.stream is None:
                self.start()
            self.serials.append(serial)

    def close(self, serial: LVSerial) -> None:
        with self.lock:
            self.serials.remove(serial)
            if not self.serials and self.stream is not None:
                self.end()

    def write(self, data: bytes) -> None:
        with self.lock:
            if self.stream is None:
                raise EOFError("The console ended")
            self.stream.write(data)

    def start(self) -> None:
        stream = LVStream(self.machine.conn)
        # With qemu:///system the console's pty is only accessible to the qemu user, so it's opened through libvirt.
        self.machine.domain.openConsole(
            None,  # type: ignore
            stream.stream,
            lv.VIR_DOMAIN_CONSOLE_FORCE,
        )
        self.stream = stream
        stream.stream.eventAddCallback(
            lv.VIR_STREAM_EVENT_READABLE
            | lv.VIR_STREAM_EVENT_ERROR
            | lv.VIR_STREAM_EVENT_HANGUP,
            self.on_event,
            None,
        )

    def end(self) -> None:
        assert self.stream is not None
        self.stream.stream.eventRemoveCallback()
        self.stream.abort()
        self.stream = None
        self.receive(b"")

    def on_event(self, stream: lv.virStream, events: int, opaque: Any) -> None:
        with self.lock:
            if self.stream is None:
                return
            data = (
                stream.recv(CHUNK_SIZE)
                if events & lv.VIR_STREAM_EVENT_READABLE
                else b""
            )
            # It returns -2 (despite its annotation) when there's nothing to read right now.
            if isinstance(data, int):
                return
            if not data:
                self.end()
                return
            self.receive(data)

    # An empty `data` means it ended.
    def receive(self, data: bytes) -> None:
        for serial in self.serials:
            serial.receive(data)


class LVSerial(Serial):
    def __init__(self, console: LVConsole) -> None:
        self.console = console
        self.data = b""
        self.ended = False
        self.received = threading.Condition()

    @override
    def create(self) -> None:
        self.console.open(self)

    @override
    def destroy(self) -> None:
        self.console.close(self)

    @override
    def read(self, size: int | None = None, timeout: float = 0) -> bytes:
        deadline = time.time() + timeout
        with self.received:
            self.received.wait_for(
                lambda: self.data or self.ended, max(0, deadline - time.time())
            )
            if not self.data and self.ended:
                raise EOFError
            size = len(self.data) if size is None else size
            result, self.data = self.data[:size], self.data[size:]
            return result

    @override
    def write(self, data: bytes) -> None:
        self.console.write(data)

    @override
    def close(self) -> None:
        self.destroy()

    # An empty `data` means the console ended, which it stays for this serial (even if the console opens again).
    def receive(self, data: bytes) -> None:
        with self.received:
            if self.ended:
                return
            self.data += data
            self.ended = not data
            self.received.notify_all()
