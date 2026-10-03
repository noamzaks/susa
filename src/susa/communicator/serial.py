from __future__ import annotations

from typing_extensions import override

from susa.communicator.login import Login
from susa.communicator.shell import ShellCommunicator
from susa.core.machine import SerialAccessible
from susa.core.stream import InputOutputStream


class SerialCommunicator(ShellCommunicator):
    def __init__(self, machine: SerialAccessible, login: Login | None = None) -> None:
        super().__init__(login)
        self.machine = machine

    @override
    def open_stream(self) -> InputOutputStream:
        serial = self.machine.serial()
        serial.create()
        return serial
