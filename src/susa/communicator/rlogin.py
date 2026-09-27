from __future__ import annotations

from typing_extensions import override

from susa.communicator.shell import Prelude, ShellCommunicator, login
from susa.communicator.terminal import ProcessTerminal, Terminal


class RloginCommunicator(ShellCommunicator):
    """A shell over the `rlogin` client as `username`, giving `password` (by default) if asked for one."""

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        prelude: Prelude | None = None,
    ) -> None:
        super().__init__(prelude or login(password))
        self.host = host
        self.username = username

    @override
    def open_terminal(self) -> Terminal:
        # 8-bit clean, with no escape character (which would otherwise be intercepted in the data).
        return ProcessTerminal("rlogin", "-8", "-E", "-l", self.username, self.host)
