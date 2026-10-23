from __future__ import annotations

import shlex

from typing_extensions import override

from susa.communicators.login import Login
from susa.communicators.shell import ShellCommunicator
from susa.core.communicator import HOST, AsyncCommandRunner, AsyncCommandStream
from susa.core.stream import InputOutputStream


class RloginCommunicator(ShellCommunicator):
    def __init__(
        self,
        ip: str,
        username: str,
        password: str,
        host: AsyncCommandRunner | None = None,
    ) -> None:
        # rlogind gets the username from the client, and asks only for the password.
        super().__init__(Login(password))
        self.ip = ip
        self.username = username
        self.host = host or HOST.get()

    @override
    def open_stream(self) -> InputOutputStream:
        # 8-bit clean, with no escape character (which would otherwise be intercepted in the data).
        command = ["rlogin", "-8", "-E", "-l", self.username, self.ip]
        return AsyncCommandStream(self.host.start(shlex.join(command)))
