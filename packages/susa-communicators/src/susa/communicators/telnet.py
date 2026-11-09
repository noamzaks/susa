from __future__ import annotations

import shlex

from typing_extensions import override

from susa.communicators.login import Login
from susa.communicators.shell import ShellCommunicator
from susa.core.communicator import HOST, AsyncCommandRunner, AsyncCommandStream
from susa.core.stream import InputOutputStream


class TelnetCommunicator(ShellCommunicator):
    def __init__(
        self,
        ip: str,
        username: str,
        password: str,
        port: int = 23,
        host: AsyncCommandRunner | None = None,
    ) -> None:
        super().__init__(Login(password, username))
        self.ip = ip
        self.port = port
        self.host = host or HOST.get()

    @override
    def open_stream(self) -> InputOutputStream:
        command = ["telnet", "-8", "-E", "-c", self.ip, str(self.port)]
        return AsyncCommandStream(self.host.start(shlex.join(command)))
