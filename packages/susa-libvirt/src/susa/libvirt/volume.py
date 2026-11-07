from __future__ import annotations

import contextlib
import subprocess
import tempfile
from collections.abc import Generator
from pathlib import Path

from typing_extensions import override

from susa.core.resource import Resource
from susa.libvirt._virsh import virsh, virsh_xml
from susa.libvirt.entity import LVEntity
from susa.libvirt.volume_model import LVVolumeModel


class LVVolume(LVEntity[LVVolumeModel], Resource):
    def __init__(self, model: LVVolumeModel) -> None:
        super().__init__(model)

    @property
    def path(self) -> str:
        return virsh("vol-path", *self._arguments()).strip()

    @override
    def create(self) -> None:
        virsh_xml(self._xml(), "vol-create", self.model.get_pool())

    @override
    def destroy(self) -> None:
        virsh("vol-delete", *self._arguments())

    # Only what was written over its backing image, without internal snapshots (which hold whole memories).
    def save(self, path: str | Path) -> None:
        backing = self.model.get_backing()
        options = [] if backing is None else ["-B", backing, "-F", "qcow2"]
        with self._download() as file:
            command = ["qemu-img", "convert", "-O", "qcow2", *options, file, str(path)]
            subprocess.run(command, check=True)

    # Creates it with what `save` saved.
    def restore(self, path: str | Path) -> None:
        self.create()
        virsh("vol-upload", *self._arguments(), str(path))

    def commit(self, target: str | Path | None = None) -> None:
        with self._download() as file:
            if target is None:
                command = ["qemu-img", "commit", "-q", file]
            else:
                command = ["qemu-img", "convert", "-O", "qcow2", file, str(target)]
            subprocess.run(command, check=True)

    def _arguments(self) -> list[str]:
        return ["--pool", self.model.get_pool(), self.model.get_name()]

    # The pool's files may only be accessible to libvirt, so it hands over the volume.
    @contextlib.contextmanager
    def _download(self) -> Generator[str, None, None]:
        with tempfile.NamedTemporaryFile() as file:
            virsh("vol-download", *self._arguments(), file.name)
            yield file.name
