from __future__ import annotations

from typing_extensions import override

from susa.communicator.login import Login
from susa.communicator.process import ProcessStream
from susa.communicator.shell import ShellCommunicator
from susa.core.stream import InputOutputStream


class TelnetCommunicator(ShellCommunicator):
    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        port: int = 23,
    ) -> None:
        super().__init__(Login(password, username))
        self.host = host
        self.port = port

    @override
    def open_stream(self) -> InputOutputStream:
        # 8-bit clean, with no escape character (which would otherwise be intercepted in the data).
        return ProcessStream("telnet", "-8", "-E", self.host, str(self.port))
