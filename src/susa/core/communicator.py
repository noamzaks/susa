from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from subprocess import CompletedProcess

from typing_extensions import override

from susa.core.resource import Resource
from susa.core.stream import OutputStream


class CommandRunner(Resource):
    @abstractmethod
    def run(self, command: str, timeout: float = 60) -> CompletedProcess[bytes]: ...

    def check(self, command: str, timeout: float = 60) -> bytes:
        result = self.run(command, timeout)
        result.check_returncode()
        return result.stdout


class AsyncCommand(ABC):
    # TODO: add `stdin`.

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
        exit_code = async_command.wait(timeout)
        return CompletedProcess(
            command,
            exit_code,
            async_command.stdout.read(),
            async_command.stderr.read(),
        )


class FileTransferrer(ABC):
    @abstractmethod
    def upload(self, local: Path, remote: str) -> None: ...

    @abstractmethod
    def download(self, remote: str, local: Path) -> None: ...
