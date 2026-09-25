from typing_extensions import override

from susa.communicator.shell import Child, Prelude, ShellCommunicator, Spawn


class SSHCommunicator(ShellCommunicator):
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
    def spawn(self) -> Child:
        options = [
            "StrictHostKeyChecking=no",
            "UserKnownHostsFile=/dev/null",
            "LogLevel=ERROR",
        ]
        if self.password is not None:
            options.append("PreferredAuthentications=password,keyboard-interactive")
        child = Spawn(
            "ssh",
            [
                "-tt",
                "-p",
                str(self.port),
                *(f"-o{o}" for o in options),
                f"{self.username}@{self.host}",
            ],
        )
        if self.password is not None:
            child.expect(b"assword:")
            child.sendline(self.password.encode())
        return child
