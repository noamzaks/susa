from __future__ import annotations

from pathlib import Path

from typing_extensions import Self

from susa.libvirt.model import Model, attribute, child, node, put
from susa.libvirt.volume_model import VolumeModel


class DiskModel(Model):
    def __init__(self) -> None:
        self.element = node(
            "disk",
            None,
            # Overridden when added to a `MachineModel`.
            node("target", dev="sda"),
            device="disk",
            type="file",
        )

    def source(self, path: str | Path, format: str = "qcow2") -> Self:
        put(self.element, node("driver", name="qemu", type=format))
        put(self.element, node("source", file=str(Path(path).resolve())))

        return self

    def bus(self, bus: str) -> Self:
        attribute(child(self.element, "target"), "bus", bus)

        return self

    def volume(self, volume: VolumeModel) -> Self:
        attribute(self.element, "type", "volume")
        put(self.element, node("driver", name="qemu", type="qcow2"))
        put(
            self.element,
            node("source", pool=volume.get_pool(), volume=volume.get_name()),
        )

        return self
