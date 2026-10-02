from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from pathlib import Path
from subprocess import CompletedProcess

from typing_extensions import override

from susa.core.resource import Resource
from susa.core.stream import InputStream, OutputStream


class FileTransferrer(ABC):
    @abstractmethod
    def upload_single(self, local: Path, remote: str) -> None: ...

    @abstractmethod
    def download_single(self, remote: str, local: Path) -> None: ...

    def upload(self, files: Mapping[Path, str]) -> None:
        for local, remote in files.items():
            self.upload_single(local, remote)

    def download(self, files: Mapping[str, Path]) -> None:
        for remote, local in files.items():
            self.download_single(remote, local)


class CommandRunner(Resource, FileTransferrer):
    @abstractmethod
    def run(self, command: str, timeout: float = 60) -> CompletedProcess[bytes]: ...

    def check(self, command: str, timeout: float = 60) -> bytes:
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
    def wait(self, timeout: float = 60) -> int: ...

    @abstractmethod
    def kill(self) -> None: ...


class AsyncCommandRunner(CommandRunner):
    @abstractmethod
    def start(self, command: str) -> AsyncCommand: ...

    @override
    def run(self, command: str, timeout: float = 60) -> CompletedProcess[bytes]:
        async_command = self.start(command)
        async_command.stdin.close()
        exit_code = async_command.wait(timeout)
        return CompletedProcess(
            command,
            exit_code,
            async_command.stdout.read_all(timeout),
            async_command.stderr.read_all(timeout),
        )
