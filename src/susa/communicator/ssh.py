from __future__ import annotations

from typing_extensions import override

from susa.communicator.shell import Prelude, ShellCommunicator
from susa.communicator.terminal import ProcessTerminal, Terminal

SSH_OPTIONS = (
    "StrictHostKeyChecking=no",
    "UserKnownHostsFile=/dev/null",
    "LogLevel=ERROR",
)


class SSHCommunicator(ShellCommunicator):
    """A shell over `ssh` (with a password, which OpenSSH asks for with a known prompt, or keys)."""

    def __init__(
        self,
        host: str,
        username: str,
        password: str | None = None,
        port: int = 22,
        prelude: Prelude | None = None,
    ) -> None:
        super().__init__(prelude)
        self.host = host
        self.username = username
        self.password = password
        self.port = port

    @override
    def open_terminal(self) -> Terminal:
        options = list(SSH_OPTIONS)
        if self.password is not None:
            options.append("PreferredAuthentications=password,keyboard-interactive")
        terminal = ProcessTerminal(
            "ssh",
            "-tt",
            f"-p{self.port}",
            *(f"-o{o}" for o in options),
            f"{self.username}@{self.host}",
        )
        if self.password is not None:
            # Unlike getty, ssh discards input sent before its prompt, so wait for it.
            terminal.expect(b"assword:")
            terminal.sendline(self.password.encode())
        return terminal
