from __future__ import annotations

from pathlib import Path

from typing_extensions import Self

from susa.libvirt.model import LVModel, attribute, node, put
from susa.libvirt.volume_model import LVVolumeModel


class LVDiskModel(LVModel):
    def __init__(self) -> None:
        self.element = node("disk", attrs={"device": "disk", "type": "file"})

    def source(self, path: str | Path, format: str = "qcow2") -> Self:
        put(self.element, node("driver", attrs={"name": "qemu", "type": format}))
        put(self.element, node("source", attrs={"file": str(Path(path).resolve())}))

        return self

    def bus(self, bus: str) -> Self:
        put(self.element, node("target", attrs={"bus": bus}))

        return self

    def volume(self, volume: LVVolumeModel) -> Self:
        attribute(self.element, "type", "volume")
        put(self.element, node("driver", attrs={"name": "qemu", "type": "qcow2"}))
        put(
            self.element,
            node(
                "source", attrs={"pool": volume.get_pool(), "volume": volume.get_name()}
            ),
        )

        return self
