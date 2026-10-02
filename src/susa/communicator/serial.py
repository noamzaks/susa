from __future__ import annotations

from typing_extensions import override

from susa.communicator.shell import Prelude, ShellCommunicator
from susa.core.machine import Serial
from susa.core.stream import InputOutputStream


class SerialCommunicator(ShellCommunicator):
    def __init__(self, serial: Serial, prelude: Prelude | None = None) -> None:
        super().__init__(prelude)
        self.serial = serial

    @override
    def open_stream(self) -> InputOutputStream:
        self.serial.create()
        return self.serial
