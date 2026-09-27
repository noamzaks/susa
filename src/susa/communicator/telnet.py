from __future__ import annotations

from typing_extensions import override

from susa.communicator.shell import Prelude, ShellCommunicator, login
from susa.communicator.terminal import ProcessTerminal, Terminal


class TelnetCommunicator(ShellCommunicator):
    """A shell over the `telnet` client, logging in (by default) with `username` and `password`."""

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        port: int = 23,
        prelude: Prelude | None = None,
    ) -> None:
        super().__init__(prelude or login(password, username))
        self.host = host
        self.port = port

    @override
    def open_terminal(self) -> Terminal:
        # 8-bit clean, with no escape character (which would otherwise be intercepted in the data).
        return ProcessTerminal("telnet", "-8", "-E", self.host, str(self.port))
