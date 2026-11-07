from __future__ import annotations

import shlex

from typing_extensions import override

from susa.core.communicator import HOST, CommandRunner
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

    # Into the image backing it, or into an image of its own at the target (a path on the host, where its files are).
    def commit(
        self, target: str | None = None, host: CommandRunner | None = None
    ) -> None:
        path = shlex.quote(self.path)
        if target is None:
            command = f"qemu-img commit -q {path}"
        else:
            command = f"qemu-img convert -O qcow2 {path} {shlex.quote(target)}"
        (host or HOST.get()).check(command)

    def _arguments(self) -> list[str]:
        return ["--pool", self.model.get_pool(), self.model.get_name()]
