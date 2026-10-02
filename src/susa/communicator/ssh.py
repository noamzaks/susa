from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Literal

from typing_extensions import override

from susa.communicator.process import ProcessStream
from susa.communicator.shell import Prelude, ShellCommunicator
from susa.core.stream import InputOutputStream

OPTIONS = ("StrictHostKeyChecking=no", "UserKnownHostsFile=/dev/null", "LogLevel=ERROR")
TRANSFER_TIMEOUT = 300


class SSHCommunicator(ShellCommunicator):
    def __init__(
        self,
        host: str,
        username: str,
        password: str | None = None,
        port: int = 22,
        file_transfer: Literal["sftp", "scp", "shell"] = "sftp",
        prelude: Prelude | None = None,
    ) -> None:
        super().__init__(prelude)
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.file_transfer = file_transfer
        self.askpass: Path | None = None

    @override
    def create(self) -> None:
        if self.password is not None:
            # ssh reads passwords from the terminal only after prompting (discarding anything sent before), so
            # instead it's given one by a program.
            fd, path = tempfile.mkstemp(prefix="susa-askpass-")
            with os.fdopen(fd, "w") as f:
                f.write('#!/bin/sh\nprintf "%s\\n" "$SUSA_PASSWORD"\n')
            os.chmod(path, 0o700)
            self.askpass = Path(path)
        super().create()

    @override
    def destroy(self) -> None:
        super().destroy()
        if self.askpass is not None:
            self.askpass.unlink()
            self.askpass = None

    def environment(self) -> dict[str, str]:
        env = dict(os.environ)
        if self.password is not None:
            assert self.askpass is not None
            env |= {
                "SSH_ASKPASS": str(self.askpass),
                "SSH_ASKPASS_REQUIRE": "force",
                "SUSA_PASSWORD": self.password,
            }
        return env

    def options(self) -> list[str]:
        return [f"-o{option}" for option in OPTIONS]

    @override
    def open_stream(self) -> InputOutputStream:
        return ProcessStream(
            "ssh",
            "-tt",
            f"-p{self.port}",
            *self.options(),
            f"{self.username}@{self.host}",
            env=self.environment(),
        )

    def scp(self, source: str, destination: str) -> None:
        subprocess.run(
            [
                "scp",
                "-q",
                "-s" if self.file_transfer == "sftp" else "-O",
                f"-P{self.port}",
                *self.options(),
                source,
                destination,
            ],
            env=self.environment(),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=True,
            timeout=TRANSFER_TIMEOUT,
        )

    @override
    def write_file(self, data: bytes, remote: str) -> None:
        if self.file_transfer == "shell":
            return super().write_file(data, remote)
        with tempfile.NamedTemporaryFile() as local:
            local.write(data)
            local.flush()
            self.scp(local.name, f"{self.username}@{self.host}:{remote}")

    @override
    def read_file(self, remote: str) -> bytes:
        if self.file_transfer == "shell":
            return super().read_file(remote)
        with tempfile.TemporaryDirectory() as directory:
            local = Path(directory) / "file"
            self.scp(f"{self.username}@{self.host}:{remote}", str(local))
            return local.read_bytes()
