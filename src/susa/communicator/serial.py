from __future__ import annotations

from typing_extensions import override

from susa.communicator.shell import Prelude, ShellCommunicator
from susa.communicator.terminal import StreamTerminal, Terminal
from susa.core.machine import Serial


class SerialCommunicator(ShellCommunicator):
    """A shell over `serial`, which it takes ownership of."""

    def __init__(self, serial: Serial, prelude: Prelude | None = None) -> None:
        super().__init__(prelude)
        self.serial = serial

    @override
    def open_terminal(self) -> Terminal:
        return StreamTerminal(self.serial)

    @override
    def destroy(self) -> None:
        super().destroy()
        self.serial.destroy()
