from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class LinkedClone:
    def __init__(self, path: str | Path, source: str | Path) -> None:
        subprocess.run(
            [
                "qemu-img",
                "create",
                "-f",
                "qcow2",
                "-b",
                str(source),
                "-B",
                "qcow2",
                str(path),
            ],
            check=True,
        )

        self.source = source
        self.path = path

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
        self.source = base
