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
        """Run `command`, returning its stdout, or raising `subprocess.CalledProcessError` if it fails."""
        result = self.run(command, timeout)
        result.check_returncode()
        return result.stdout


class AsyncCommand(ABC):
    """A command running in the background."""

    @property
    @abstractmethod
    def stdout(self) -> OutputStream: ...

    @property
    @abstractmethod
    def stderr(self) -> OutputStream: ...

    @abstractmethod
    def poll(self) -> int | None:
        """The exit code, or `None` if it's still running."""

    @abstractmethod
    def wait(self, timeout: float = 60) -> int:
        """Wait for the command to finish, returning its exit code. Raises `TimeoutError` if it doesn't finish
        within `timeout` seconds."""

    @abstractmethod
    def kill(self) -> None: ...


class AsyncCommandRunner(CommandRunner):
    @abstractmethod
    def start(self, command: str) -> AsyncCommand: ...

    @override
    def run(self, command: str, timeout: float = 60) -> CompletedProcess[bytes]:
        async_command = self.start(command)
        try:
            exit_code = async_command.wait(timeout)
        except TimeoutError:
            async_command.kill()
            raise
        return CompletedProcess(
            command, exit_code, async_command.stdout.read(), async_command.stderr.read()
        )


class FileTransferrer(ABC):
    @abstractmethod
    def upload(self, local: Path, remote: str) -> None: ...

    @abstractmethod
    def download(self, remote: str, local: Path) -> None: ...
