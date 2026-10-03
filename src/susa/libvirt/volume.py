from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import libvirt as lv
from typing_extensions import override

from susa.core.resource import Resource
from susa.libvirt.entity import LVEntity
from susa.libvirt.stream import LVStream
from susa.libvirt.volume_model import VolumeModel


class LVVolume(LVEntity[lv.virStorageVol, VolumeModel], Resource):
    def __init__(self, model: VolumeModel) -> None:
        super().__init__(model)

    @property
    def path(self) -> str:
        assert self.value is not None
        return self.value.path()

    @override
    def create(self) -> None:
        assert self.value is None
        self.value = self.pool().createXML(self.xml())

    @override
    def destroy(self) -> None:
        assert self.value is not None
        self.value.delete()
        self.value = None

    @override
    def lookup(self) -> lv.virStorageVol:
        return self.pool().storageVolLookupByName(self.model.get_name())

    # Its changes, into what's backing it (under any other volumes it backs too), or else into a new image at `target`.
    def commit(self, target: str | Path | None = None) -> None:
        assert self.value is not None
        # The pool's files may only be accessible to libvirt, so it hands over the volume.
        with tempfile.NamedTemporaryFile() as file:
            stream = LVStream(self.conn)
            self.value.download(stream.stream, 0, 0)
            shutil.copyfileobj(stream.file(), file)
            stream.close()
            file.flush()
            if target is None:
                command = ["qemu-img", "commit", "-q", file.name]
            else:
                command = ["qemu-img", "convert", "-O", "qcow2", file.name, str(target)]
            subprocess.run(command, check=True)

    def pool(self) -> lv.virStoragePool:
        return self.conn.storagePoolLookupByName(self.model.get_pool())
