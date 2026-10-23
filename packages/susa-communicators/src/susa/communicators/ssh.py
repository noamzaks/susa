from __future__ import annotations

import shlex
from pathlib import Path
from typing import Literal

from typing_extensions import override

from susa.communicators.shell import ShellCommunicator
from susa.core.communicator import (
    HOST,
    AsyncCommandRunner,
    AsyncCommandStream,
    FileTransferrer,
)
from susa.core.stream import InputOutputStream


# ssh reads passwords from the terminal only after prompting, so sshpass gives them.
class SSHCommunicator(ShellCommunicator, FileTransferrer):
    OPTIONS = (
        # No configuration files (e.g. the user's).
        "-Fnone",
        "-oStrictHostKeyChecking=no",
        "-oUserKnownHostsFile=/dev/null",
        "-oLogLevel=ERROR",
    )

    def __init__(
        self,
        ip: str,
        username: str,
        password: str | None = None,
        port: int = 22,
        file_transfer: Literal["sftp", "scp"] = "sftp",
        host: AsyncCommandRunner | None = None,
    ) -> None:
        super().__init__()
        self.ip = ip
        self.username = username
        self.password = password
        self.port = port
        self.file_transfer = file_transfer
        self.host = host or HOST.get()

    @override
    def open_stream(self) -> InputOutputStream:
        login = f"{self.username}@{self.ip}"
        return AsyncCommandStream(
            self.host.start(self.command("ssh", "-tt", f"-p{self.port}", login))
        )

    @override
    def upload_single(
        self, local: Path, remote: str, timeout: float | None = None
    ) -> None:
        self.scp(str(local), f"{self.username}@{self.ip}:{remote}", timeout)

    @override
    def download_single(
        self, remote: str, local: Path, timeout: float | None = None
    ) -> None:
        self.scp(f"{self.username}@{self.ip}:{remote}", str(local), timeout)

    def scp(self, source: str, destination: str, timeout: float | None) -> None:
        protocol = "-s" if self.file_transfer == "sftp" else "-O"
        command = self.command(
            "scp", "-q", protocol, f"-P{self.port}", source, destination
        )
        self.host.check(command, timeout)

    def command(self, program: str, *args: str) -> str:
        command = shlex.join([program, *SSHCommunicator.OPTIONS, *args])
        if self.password is None:
            return command
        return f"SSHPASS={shlex.quote(self.password)} sshpass -e {command}"
