from __future__ import annotations

import logging
import subprocess
from abc import ABC, abstractmethod
from collections.abc import Mapping
from pathlib import Path
from subprocess import CompletedProcess

from typing_extensions import override

from susa.core.resource import Resource
from susa.core.stream import FileStream, InputOutputStream, InputStream, OutputStream
from susa.core.variable import Variable
from susa.utilities.environment import default
from susa.utilities.generic import Deadline


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


class AsyncCommandStream(InputOutputStream):
    def __init__(self, command: AsyncCommand) -> None:
        self.command = command

    @override
    def read(self, size: int | None = None, timeout: float | None = 0) -> bytes:
        return self.command.stdout.read(size, timeout)

    @override
    def write(self, data: bytes) -> None:
        self.command.stdin.write(data)

    @override
    def close(self) -> None:
        self.command.stdin.close()
        self.command.kill()
        self.command.wait()


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
        stdout = async_command.stdout.read_all_in_background()
        stderr = async_command.stderr.read_all_in_background()
        try:
            exit_code = async_command.wait(deadline.remaining())
        except TimeoutError:
            # Which also ends its output.
            async_command.kill()
            raise
        result = CompletedProcess(
            command,
            exit_code,
            stdout.result(deadline.remaining()),
            stderr.result(deadline.remaining()),
        )
        logging.debug(
            "%.200r exited with %d, writing %.1000r and %.1000r to stderr",
            command,
            exit_code,
            result.stdout,
            result.stderr,
        )
        return result


class HostAsyncCommandRunner(AsyncCommandRunner):
    @override
    def create(self) -> None:
        pass

    @override
    def destroy(self) -> None:
        pass

    @override
    def start(self, command: str) -> AsyncCommand:
        return HostAsyncCommand(command)


# Killing it kills the shell, so the commands it didn't replace itself with (e.g. in `a; b`) keep running.
class HostAsyncCommand(AsyncCommand):
    def __init__(self, command: str) -> None:
        logging.debug("Running %.200r on this system", command)
        self.process = subprocess.Popen(
            command,
            shell=True,
            bufsize=0,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert self.process.stdin and self.process.stdout and self.process.stderr
        self._stdin = FileStream(self.process.stdin)
        self._stdout = FileStream(self.process.stdout)
        self._stderr = FileStream(self.process.stderr)

    @property
    @override
    def stdin(self) -> InputStream:
        return self._stdin

    @property
    @override
    def stdout(self) -> OutputStream:
        return self._stdout

    @property
    @override
    def stderr(self) -> OutputStream:
        return self._stderr

    @override
    def poll(self) -> int | None:
        return self.process.poll()

    @override
    def wait(self, timeout: float | None = None) -> int:
        try:
            return self.process.wait(timeout)
        except subprocess.TimeoutExpired as e:
            raise TimeoutError(
                f"{self.process.args!r} didn't exit within {timeout} seconds"
            ) from e

    @override
    def kill(self) -> None:
        self.process.kill()


# What commands run on (by default) when they run "on the host", e.g. clients of remote shells or ping.
HOST = Variable[AsyncCommandRunner](
    default_factory=lambda: (
        default("host", AsyncCommandRunner) or HostAsyncCommandRunner()
    )
)
