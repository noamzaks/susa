from __future__ import annotations

from typing import TYPE_CHECKING

from typing_extensions import override

from susa.core.machine import Serial
from susa.libvirt.stream import LVStream

if TYPE_CHECKING:
    from susa.libvirt.machine import LVMachine


# The machine's (first) console, which has one user at a time.
class LVSerial(LVStream, Serial):
    def __init__(self, machine: LVMachine) -> None:
        super().__init__(machine.conn)
        self.machine = machine

    @override
    def create(self) -> None:
        # With qemu:///system the console's pty is only accessible to the qemu user, so it's opened through libvirt.
        self.machine.domain.openConsole(None, self.stream)  # type: ignore

    @override
    def destroy(self) -> None:
        self.stream.abort()

    @override
    def close(self) -> None:
        self.destroy()
