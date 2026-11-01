from __future__ import annotations

import subprocess
import tempfile
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

    def commit(self, target: str | Path | None = None) -> None:
        # The pool's files may only be accessible to libvirt, so it hands over the volume.
        with tempfile.NamedTemporaryFile() as file:
            virsh("vol-download", *self._arguments(), file.name)
            if target is None:
                command = ["qemu-img", "commit", "-q", file.name]
            else:
                command = ["qemu-img", "convert", "-O", "qcow2", file.name, str(target)]
            subprocess.run(command, check=True)

    def _arguments(self) -> list[str]:
        return ["--pool", self.model.get_pool(), self.model.get_name()]
