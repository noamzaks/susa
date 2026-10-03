from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from pathlib import Path
from subprocess import CompletedProcess

from typing_extensions import override

from susa.core.resource import Resource
from susa.core.stream import InputStream, OutputStream
from susa.utilities.generic import Deadline

# Timeouts are in seconds, where `None` waits as long as it takes.


class FileTransferrer(ABC):
    @abstractmethod
    def upload_single(
        self, local: Path, remote: str, timeout: float | None = None
    ) -> None: ...

    @abstractmethod
    def download_single(
        self, remote: str, local: Path, timeout: float | None = None
    ) -> None: ...

    def upload(self, files: Mapping[Path, str], timeout: float | None = None) -> None:
        deadline = Deadline(timeout)
        for local, remote in files.items():
            self.upload_single(local, remote, deadline.remaining())

    def download(self, files: Mapping[str, Path], timeout: float | None = None) -> None:
        deadline = Deadline(timeout)
        for remote, local in files.items():
            self.download_single(remote, local, deadline.remaining())


class CommandRunner(Resource):
    @abstractmethod
    def run(
        self, command: str, timeout: float | None = None
    ) -> CompletedProcess[bytes]: ...

    def check(self, command: str, timeout: float | None = None) -> bytes:
        result = self.run(command, timeout)
        result.check_returncode()
        return result.stdout


class AsyncCommand(ABC):
    @property
    @abstractmethod
    def stdin(self) -> InputStream: ...

    @property
    @abstractmethod
    def stdout(self) -> OutputStream: ...

    @property
    @abstractmethod
    def stderr(self) -> OutputStream: ...

    @abstractmethod
    def poll(self) -> int | None: ...

    @abstractmethod
    def wait(self, timeout: float | None = None) -> int: ...

    @abstractmethod
    def kill(self) -> None: ...


class AsyncCommandRunner(CommandRunner):
    @abstractmethod
    def start(self, command: str) -> AsyncCommand: ...

    @override
    def run(
        self, command: str, timeout: float | None = None
    ) -> CompletedProcess[bytes]:
        deadline = Deadline(timeout)
        async_command = self.start(command)
        async_command.stdin.close()
        exit_code = async_command.wait(deadline.remaining())
        stdout = async_command.stdout.read_all(deadline.remaining())
        stderr = async_command.stderr.read_all(deadline.remaining())
        return CompletedProcess(command, exit_code, stdout, stderr)
