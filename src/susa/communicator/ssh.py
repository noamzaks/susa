from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Literal

from typing_extensions import override

from susa.communicator.process import ProcessStream
from susa.communicator.shell import ShellCommunicator
from susa.core.communicator import FileTransferrer
from susa.core.stream import InputOutputStream

OPTIONS = [
    "-oStrictHostKeyChecking=no",
    "-oUserKnownHostsFile=/dev/null",
    "-oLogLevel=ERROR",
]


# The password (if any) is given by sshpass, since ssh reads it from the terminal only after prompting.
class SSHCommunicator(ShellCommunicator, FileTransferrer):
    def __init__(
        self,
        host: str,
        username: str,
        password: str | None = None,
        port: int = 22,
        file_transfer: Literal["sftp", "scp"] = "sftp",
    ) -> None:
        super().__init__()
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.file_transfer = file_transfer

    @override
    def open_stream(self) -> InputOutputStream:
        command = self.command(
            "ssh", "-tt", f"-p{self.port}", f"{self.username}@{self.host}"
        )
        return ProcessStream(*command, env=self.environment())

    @override
    def upload_single(
        self, local: Path, remote: str, timeout: float | None = None
    ) -> None:
        self.scp(str(local), f"{self.username}@{self.host}:{remote}", timeout)

    @override
    def download_single(
        self, remote: str, local: Path, timeout: float | None = None
    ) -> None:
        self.scp(f"{self.username}@{self.host}:{remote}", str(local), timeout)

    # Over SFTP, or else legacy SCP.
    def scp(self, source: str, destination: str, timeout: float | None) -> None:
        protocol = "-s" if self.file_transfer == "sftp" else "-O"
        subprocess.run(
            self.command("scp", "-q", protocol, f"-P{self.port}", source, destination),
            env=self.environment(),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=True,
            timeout=timeout,
        )

    def command(self, program: str, *args: str) -> list[str]:
        sshpass = [] if self.password is None else ["sshpass", "-e"]
        return [*sshpass, program, *OPTIONS, *args]

    def environment(self) -> dict[str, str]:
        if self.password is None:
            return dict(os.environ)
        return {**os.environ, "SSHPASS": self.password}
