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

        self.path = path

    def commit(self) -> None:
        subprocess.run(
            ["qemu-img", "commit", self.path],
            check=True,
        )
