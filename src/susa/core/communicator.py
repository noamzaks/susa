from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from typing_extensions import override

from susa.core.resource import Resource
from susa.core.stream import Stream


@dataclass(frozen=True)
class CommandResult:
    stdout: bytes
    stderr: bytes
    exit_code: int


class CommandRunner(Resource):
    @abstractmethod
    def run(self, command: str, timeout: float = 60) -> CommandResult: ...

    def check(self, command: str, timeout: float = 60) -> bytes:
        """Run `command`, returning its stdout, or raising `RuntimeError` if it fails."""
        result = self.run(command, timeout)
        if result.exit_code != 0:
            raise RuntimeError(
                f"{command!r} failed with {result.exit_code}: {result.stderr!r}"
            )
        return result.stdout


class Process(ABC):
    """A command running in the background."""

    @property
    @abstractmethod
    def stdout(self) -> Stream: ...

    @property
    @abstractmethod
    def stderr(self) -> Stream: ...

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
    def start(self, command: str) -> Process: ...

    @override
    def run(self, command: str, timeout: float = 60) -> CommandResult:
        process = self.start(command)
        try:
            exit_code = process.wait(timeout)
        except TimeoutError:
            process.kill()
            raise
        return CommandResult(process.stdout.read(), process.stderr.read(), exit_code)


class FileTransferrer(ABC):
    @abstractmethod
    def upload(self, local: Path, remote: str) -> None: ...

    @abstractmethod
    def download(self, remote: str, local: Path) -> None: ...
