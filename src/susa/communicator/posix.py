from __future__ import annotations

import gzip
import shlex
import tarfile
from collections.abc import Mapping
from io import BytesIO
from pathlib import Path

from typing_extensions import override

from susa.core.communicator import CommandRunner

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


# File transfers built on POSIX commands, over two primitives (`write_file` and `read_file`) that a faster channel may
# replace (e.g. SSH's scp).
class PosixFileTransfer(CommandRunner):
    def write_file(self, data: bytes, remote: str) -> None:
        # Compressed, and written with `printf` (there may be no decoder like `base64`, e.g. on FreeBSD 10).
        compressed = gzip.compress(data)
        temporary = shlex.quote(self.temporary_file())
        for i in range(0, len(compressed), WRITE_CHUNK_SIZE):
            chunk = compressed[i : i + WRITE_CHUNK_SIZE]
            self.check(" &&\n".join(printf_lines(chunk, temporary)))
        self.check(f"gzip -dc < {temporary} > {shlex.quote(remote)} && rm {temporary}")

    def read_file(self, remote: str) -> bytes:
        return gzip.decompress(self.check(f"gzip -c {shlex.quote(remote)}"))

    def temporary_file(self) -> str:
        return self.check("mktemp").decode().strip()

    @override
    def upload_single(self, local: Path, remote: str) -> None:
        self.write_file(local.read_bytes(), remote)

    @override
    def download_single(self, remote: str, local: Path) -> None:
        local.write_bytes(self.read_file(remote))

    @override
    def upload(self, files: Mapping[Path, str]) -> None:
        archive = BytesIO()
        with tarfile.open(fileobj=archive, mode="w") as tar:
            for local, remote in files.items():
                data = local.read_bytes()
                # Unlike `tar.add`, this keeps absolute names.
                info = tarfile.TarInfo(remote)
                info.size, info.mode = len(data), local.stat().st_mode
                tar.addfile(info, BytesIO(data))
        temporary = self.temporary_file()
        self.write_file(archive.getvalue(), temporary)
        # `-P` keeps each given path, absolute or relative.
        self.check(f"tar -xPf {shlex.quote(temporary)} && rm {shlex.quote(temporary)}")

    @override
    def download(self, files: Mapping[str, Path]) -> None:
        temporary = self.temporary_file()
        paths = " ".join(map(shlex.quote, files))
        self.check(f"tar -cPf {shlex.quote(temporary)} {paths}")
        archive = self.read_file(temporary)
        self.check(f"rm {shlex.quote(temporary)}")
        with tarfile.open(fileobj=BytesIO(archive)) as tar:
            for member in tar.getmembers():
                extracted = tar.extractfile(member)
                assert extracted is not None
                files[member.name].write_bytes(extracted.read())
