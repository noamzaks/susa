from __future__ import annotations

import gzip
import shlex
import tarfile
from abc import ABC, abstractmethod
from collections.abc import Mapping
from io import BytesIO
from pathlib import Path
from subprocess import CompletedProcess

from typing_extensions import override

from susa.core.resource import Resource
from susa.core.stream import InputStream, OutputStream

PRINTF_CHUNK_SIZE = 512
WRITE_CHUNK_SIZE = 1 << 15


def printf_lines(data: bytes, target: str) -> list[str]:
    # Short enough lines for a terminal, with nothing but POSIX `printf`.
    return [
        "printf '"
        + "".join(
            chr(b) if chr(b).isalnum() and b < 128 else f"\\{b:03o}"
            for b in data[i : i + PRINTF_CHUNK_SIZE]
        )
        + f"' >> {target}"
        for i in range(0, len(data), PRINTF_CHUNK_SIZE)
    ]


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

    def write_file(self, data: bytes, remote: str) -> None:
        target = shlex.quote(remote)
        self.check(f": > {target}")
        for i in range(0, len(data), WRITE_CHUNK_SIZE):
            self.check(
                " &&\n".join(printf_lines(data[i : i + WRITE_CHUNK_SIZE], target))
            )

    def upload_compressed(self, data: bytes, extract: str) -> None:
        temporary = shlex.quote(self.check("mktemp").decode().strip())
        self.write_file(data, temporary)
        self.check(f"{extract} < {temporary} && rm {temporary}")

    @override
    def upload_single(self, local: Path, remote: str) -> None:
        self.upload_compressed(
            gzip.compress(local.read_bytes()), f"gzip -dc > {shlex.quote(remote)}"
        )

    @override
    def download_single(self, remote: str, local: Path) -> None:
        local.write_bytes(gzip.decompress(self.check(f"gzip -c {shlex.quote(remote)}")))

    @override
    def upload(self, files: Mapping[Path, str]) -> None:
        archive = BytesIO()
        with tarfile.open(fileobj=archive, mode="w:gz") as tar:
            for local, remote in files.items():
                data = local.read_bytes()
                # Unlike `tar.add`, this keeps absolute names.
                info = tarfile.TarInfo(remote)
                info.size, info.mode = len(data), local.stat().st_mode
                tar.addfile(info, BytesIO(data))
        self.upload_compressed(archive.getvalue(), "tar -xzPf -")

    @override
    def download(self, files: Mapping[str, Path]) -> None:
        archive = self.check(f"tar -czPf - {' '.join(map(shlex.quote, files))}")
        with tarfile.open(fileobj=BytesIO(archive), mode="r:gz") as tar:
            for member in tar.getmembers():
                extracted = tar.extractfile(member)
                assert extracted is not None
                files[member.name].write_bytes(extracted.read())


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
