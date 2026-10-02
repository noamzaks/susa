from __future__ import annotations

from typing_extensions import override

from susa.communicator.process import ProcessStream
from susa.communicator.shell import Login, NetworkCommunicator
from susa.core.machine import Machine
from susa.core.stream import InputOutputStream


class RloginCommunicator(NetworkCommunicator):
    def __init__(
        self,
        machine: Machine | str,
        username: str,
        password: str,
    ) -> None:
        # rlogind gets the username from the client, and asks only for the password.
        super().__init__(machine, Login(password))
        self.username = username

    @override
    def open_stream(self) -> InputOutputStream:
        # 8-bit clean, with no escape character (which would otherwise be intercepted in the data).
        return ProcessStream("rlogin", "-8", "-E", "-l", self.username, self.host)
