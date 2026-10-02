from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from typing_extensions import override

from susa.core.resource import Resource


class LinkedClone(Resource):
    def __init__(self, path: str | Path, source: str | Path) -> None:
        self.path = Path(path)
        self.source = Path(source)

    @override
    def create(self) -> None:
        subprocess.run(
            [
                "qemu-img",
                "create",
                "-f",
                "qcow2",
                "-b",
                str(self.source),
                "-B",
                "qcow2",
                str(self.path),
            ],
            check=True,
        )

    @override
    def destroy(self) -> None:
        self.path.unlink()

    def commit(self, target: str | Path | None) -> None:
        if target is not None:
            shutil.copyfile(self.source, target)
            self.rebase(target)

        subprocess.run(
            ["qemu-img", "commit", self.path],
            check=True,
        )

    def rebase(self, base: str | Path) -> None:
        subprocess.run(
            ["qemu-img", "rebase", "-f", "qcow2", "-b", base, "-B", "qcow2", self.path],
            check=True,
        )
        self.source = Path(base)
