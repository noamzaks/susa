from __future__ import annotations

import gzip
import shlex
import tarfile
import time
from collections.abc import Mapping
from io import BytesIO
from pathlib import Path

from typing_extensions import override

from susa.core.communicator import (
    AsyncCommand,
    AsyncCommandRunner,
    CommandRunner,
    FileTransferrer,
)
from susa.core.stream import InputStream, OutputStream
from susa.utilities.generic import Deadline

PRINTF_CHUNK_SIZE = 512
WRITE_CHUNK_SIZE = 1 << 15
POLL_INTERVAL = 0.2


# What Unix commands do over a communicator that runs them (in one shell, e.g. a `ShellCommunicator`): commands in the
# background with their own input and outputs, and file transfers. It uses the commands found everywhere, though gzip,
# tar and mktemp aren't in the Unix spec.
class UnixCommunicator(AsyncCommandRunner, FileTransferrer):
    def __init__(self, communicator: CommandRunner) -> None:
        self.communicator = communicator
        # Where commands keep their input and output.
        self.directory: str | None = None

    @override
    def create(self) -> None:
        assert self.directory is None
        self.directory = self.communicator.check("mktemp -d").decode().strip()

    @override
    def destroy(self) -> None:
        assert self.directory is not None
        self.communicator.check(f"rm -r {shlex.quote(self.directory)}")
        self.directory = None

    @override
    def start(self, command: str) -> UnixCommand:
        return UnixCommand(self, command)

    # Its process ID.
    def background(self, command: str) -> str:
        output = self.communicator.check(f"{command} & echo $!")
        # Interactive shells may also print the job number (e.g. "[1] 1234").
        return output.split()[-1].decode()

    @override
    def upload_single(
        self, local: Path, remote: str, timeout: float | None = None
    ) -> None:
        self.write_file(local.read_bytes(), remote, timeout)

    @override
    def download_single(
        self, remote: str, local: Path, timeout: float | None = None
    ) -> None:
        local.write_bytes(self.read_file(remote, timeout))

    @override
    def upload(self, files: Mapping[Path, str], timeout: float | None = None) -> None:
        deadline = Deadline(timeout)
        archive = BytesIO()
        with tarfile.open(fileobj=archive, mode="w") as tar:
            for local, remote in files.items():
                # Unlike `tar.add`, this keeps absolute names (and not the local owner).
                stat = local.stat()
                info = tarfile.TarInfo(remote)
                info.size, info.mode = stat.st_size, stat.st_mode
                info.mtime = int(stat.st_mtime)
                with local.open("rb") as file:
                    tar.addfile(info, file)
        temporary = self.temporary_file()
        self.write_file(archive.getvalue(), temporary, deadline.remaining())
        # `-P` keeps each given path, absolute or relative.
        quoted = shlex.quote(temporary)
        self.communicator.check(
            f"tar -xPf {quoted} && rm {quoted}", deadline.remaining()
        )

    @override
    def download(self, files: Mapping[str, Path], timeout: float | None = None) -> None:
        deadline = Deadline(timeout)
        temporary = self.temporary_file()
        quoted = shlex.quote(temporary)
        paths = " ".join(map(shlex.quote, files))
        self.communicator.check(f"tar -cPf {quoted} {paths}", deadline.remaining())
        archive = self.read_file(temporary, deadline.remaining())
        self.communicator.check(f"rm {quoted}")
        with tarfile.open(fileobj=BytesIO(archive)) as tar:
            for member in tar.getmembers():
                extracted = tar.extractfile(member)
                assert extracted is not None
                files[member.name].write_bytes(extracted.read())

    # Compressed, and written with `printf` (there may be no decoder like `base64`, e.g. on FreeBSD 10).
    def write_file(
        self, data: bytes, remote: str, timeout: float | None = None
    ) -> None:
        deadline = Deadline(timeout)
        compressed = gzip.compress(data)
        temporary = shlex.quote(self.temporary_file())
        for i in range(0, len(compressed), WRITE_CHUNK_SIZE):
            command = printf_command(compressed[i : i + WRITE_CHUNK_SIZE], temporary)
            self.communicator.check(command, deadline.remaining())
        self.communicator.check(
            f"gzip -dc < {temporary} > {shlex.quote(remote)} && rm {temporary}",
            deadline.remaining(),
        )

    def read_file(self, remote: str, timeout: float | None = None) -> bytes:
        output = self.communicator.check(f"gzip -c {shlex.quote(remote)}", timeout)
        return gzip.decompress(output)

    def temporary_file(self) -> str:
        return self.communicator.check("mktemp").decode().strip()


# Appends the data to the target with nothing but `printf`, in lines short enough for a terminal.
def printf_command(data: bytes, target: str) -> str:
    return " &&\n".join(
        "printf '"
        + "".join(
            chr(b) if chr(b).isalnum() and b < 128 else f"\\{b:03o}"
            for b in data[i : i + PRINTF_CHUNK_SIZE]
        )
        + f"' >> {target}"
        for i in range(0, len(data), PRINTF_CHUNK_SIZE)
    )


# A command in the background, `sh -c` with its input from a FIFO and its outputs to files.
class UnixCommand(AsyncCommand):
    def __init__(self, unix: UnixCommunicator, command: str) -> None:
        self.unix = unix
        assert unix.directory is not None
        template = shlex.quote(f"{unix.directory}/command.XXXXXX")
        directory = unix.communicator.check(f"mktemp -d {template}").decode().strip()
        directory = shlex.quote(directory)
        unix.communicator.check(f"mkfifo {directory}/in")
        self.pid = unix.background(
            f"sh -c {shlex.quote(command)} < {directory}/in > {directory}/out 2> {directory}/err"
        )
        self.exit_code: int | None = None
        self._stdin = UnixInputStream(unix, f"{directory}/in")
        self._stdout = UnixOutputStream(self, f"{directory}/out")
        self._stderr = UnixOutputStream(self, f"{directory}/err")

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
        if self.exit_code is not None:
            return self.exit_code
        if self.unix.communicator.run(f"kill -0 {self.pid}").returncode == 0:
            return None
        return self.wait()

    @override
    def wait(self, timeout: float | None = None) -> int:
        # The shell only reports the exit code once.
        if self.exit_code is not None:
            return self.exit_code
        result = self.unix.communicator.run(f"wait {self.pid}", timeout)
        self.exit_code = result.returncode
        self._stdin.close()
        return self.exit_code

    @override
    def kill(self) -> None:
        self.unix.communicator.check(f"kill {self.pid}")


class UnixInputStream(InputStream):
    def __init__(self, unix: UnixCommunicator, path: str) -> None:
        self.unix = unix
        self.path = path
        # Keeps the FIFO open (so the command doesn't see its end) until it's closed.
        self.holder: str | None = unix.background(f"sleep 2147483647 > {path}")

    @override
    def write(self, data: bytes) -> None:
        self.unix.communicator.check(printf_command(data, self.path))

    @override
    def close(self) -> None:
        if self.holder is None:
            return
        self.unix.communicator.run(f"kill {self.holder}; wait {self.holder}")
        self.holder = None


class UnixOutputStream(OutputStream):
    def __init__(self, command: UnixCommand, path: str) -> None:
        self.command = command
        self.path = path
        self.offset = 0

    @override
    def read(self, size: int | None = None, timeout: float | None = 0) -> bytes:
        deadline = Deadline(timeout)
        head = "" if size is None else f" | head -c {size}"
        while True:
            finished = self.command.poll() is not None
            tail = f"tail -c +{self.offset + 1} {self.path}{head}"
            data = self.command.unix.communicator.run(tail).stdout
            if data:
                self.offset += len(data)
                return data
            if finished:
                raise EOFError
            if deadline.passed():
                return b""
            time.sleep(POLL_INTERVAL)
