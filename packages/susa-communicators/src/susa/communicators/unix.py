from __future__ import annotations

import gzip
import shlex
import tarfile
import time
from collections.abc import Mapping
from io import BytesIO
from pathlib import Path
from subprocess import CompletedProcess

from typing_extensions import override

from susa.core.communicator import (
    AsyncCommand,
    AsyncCommandRunner,
    CommandRunner,
    FileTransferrer,
)
from susa.core.stream import InputStream, OutputStream
from susa.utilities.generic import Deadline


# gzip, tar and mktemp aren't in the Unix spec, but they're everywhere.
class UnixCommunicator(AsyncCommandRunner, FileTransferrer):
    PRINTF_CHUNK_SIZE = 512

    def __init__(self, communicator: CommandRunner) -> None:
        self.communicator = communicator
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

    # Its streams are read through the same shell, so after it exited rather than while it's waited for.
    @override
    def run(
        self, command: str, timeout: float | None = None
    ) -> CompletedProcess[bytes]:
        deadline = Deadline(timeout)
        unix_command = self.start(command)
        unix_command.stdin.close()
        exit_code = unix_command.wait(deadline.remaining())
        stdout = unix_command.stdout.read_all(deadline.remaining())
        stderr = unix_command.stderr.read_all(deadline.remaining())
        return CompletedProcess(command, exit_code, stdout, stderr)

    @override
    def start(self, command: str) -> UnixCommand:
        return UnixCommand(self, command)

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

    # There may be no decoder like `base64` (e.g. on FreeBSD 10).
    def write_file(
        self, data: bytes, remote: str, timeout: float | None = None
    ) -> None:
        deadline = Deadline(timeout)
        compressed = gzip.compress(data)
        temporary = shlex.quote(self.temporary_file())
        self.append(compressed, temporary, deadline.remaining())
        self.communicator.check(
            f"gzip -dc < {temporary} > {shlex.quote(remote)} && rm {temporary}",
            deadline.remaining(),
        )

    def read_file(self, remote: str, timeout: float | None = None) -> bytes:
        output = self.communicator.check(f"gzip -c {shlex.quote(remote)}", timeout)
        return gzip.decompress(output)

    def temporary_file(self) -> str:
        return self.communicator.check("mktemp").decode().strip()

    # A command at a time, since a terminal drops what a slow shell hasn't read yet.
    def append(self, data: bytes, target: str, timeout: float | None = None) -> None:
        deadline = Deadline(timeout)
        for i in range(0, len(data), UnixCommunicator.PRINTF_CHUNK_SIZE):
            octal = "".join(
                chr(b) if chr(b).isalnum() and b < 128 else f"\\{b:03o}"
                for b in data[i : i + UnixCommunicator.PRINTF_CHUNK_SIZE]
            )
            self.communicator.check(
                f"printf '{octal}' >> {target}", deadline.remaining()
            )


class UnixCommand(AsyncCommand):
    POLL_INTERVAL = 0.2

    def __init__(self, unix: UnixCommunicator, command: str) -> None:
        self.unix = unix
        assert unix.directory is not None
        template = shlex.quote(f"{unix.directory}/command.XXXXXX")
        directory = unix.communicator.check(f"mktemp -d {template}").decode().strip()
        directory = shlex.quote(directory)
        fifo = f"{directory}/in"
        # This shell opens the FIFO's ends (first read-write, so that neither blocks) before starting the command and
        # what holds its input open, so that both have them however long they take to start.
        unix.communicator.check(
            f"mkfifo {fifo} && exec 3<> {fifo} 4> {fifo} 5< {fifo} 3<&-"
        )
        self.status = f"{directory}/status"
        self.pid = self.background(
            f"sh -c {shlex.quote(command)} <&5 > {directory}/out 2> {directory}/err",
            self.status,
        )
        holder = self.background("sleep 2147483647 >&4", "/dev/null")
        unix.communicator.check("exec 4>&- 5<&-")
        self.exit_code: int | None = None
        self._stdin = UnixInputStream(unix, fifo, holder)
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
        # It's empty until the exit code is written (at once).
        status = self.unix.communicator.run(f"cat {self.status} 2> /dev/null").stdout
        if not status:
            return None
        self.exit_code = int(status)
        self._stdin.close()
        return self.exit_code

    @override
    def wait(self, timeout: float | None = None) -> int:
        deadline = Deadline(timeout)
        while (exit_code := self.poll()) is None:
            deadline.test("The command didn't exit")
            time.sleep(UnixCommand.POLL_INTERVAL)
        return exit_code

    @override
    def kill(self) -> None:
        self.unix.communicator.check(f"kill {self.pid}")

    # From a subshell, so that it isn't one of this shell's jobs, which interactive shells print about (e.g. "[1] 1234",
    # or that one finished). The subshell writes its exit code to `status`, and stops holding the output (so that it's
    # read) once it started.
    def background(self, command: str, status: str) -> str:
        waiter = f"{command} 4>&- 5<&- & echo $!; exec > /dev/null 4>&- 5<&-; wait $!; echo $? > {status}"
        return self.unix.communicator.check(f"echo $( ({waiter}) & )").decode().strip()


class UnixInputStream(InputStream):
    # The holder keeps the FIFO open (so the command doesn't see its end) until it's closed.
    def __init__(self, unix: UnixCommunicator, path: str, holder: str) -> None:
        self.unix = unix
        self.path = path
        self.holder: str | None = holder

    @override
    def write(self, data: bytes) -> None:
        self.unix.append(data, self.path)

    @override
    def close(self) -> None:
        if self.holder is None:
            return
        self.unix.communicator.check(f"kill {self.holder}")
        self.holder = None


class UnixOutputStream(OutputStream):
    POLL_INTERVAL = 0.2

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
            time.sleep(UnixOutputStream.POLL_INTERVAL)
