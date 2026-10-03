from __future__ import annotations

from pathlib import Path

import pydantic_libvirt.storagevol as lvstoragevol
from typing_extensions import Self

from susa.libvirt.model import Model
from susa.utilities.generic import random_id


# A qcow2 volume in a storage pool, e.g. an overlay of a base image (which libvirt places, and deletes with it).
class VolumeModel(Model[lvstoragevol.vol]):
    def __init__(
        self, name: str | None = None, xml_model: lvstoragevol.vol | None = None
    ) -> None:
        self.xml_model = xml_model or lvstoragevol.vol(
            name=lvstoragevol.name(value=name or f"susa-{random_id(10)}"),
            target=lvstoragevol.target(format=lvstoragevol.format(type="qcow2")),
        )
        # The volume's XML doesn't say which pool it's in.
        self.pool_name = "default"

    def name(self, name: str) -> Self:
        self.xml_model.name = lvstoragevol.name(value=name)

        return self

    def pool(self, pool: str) -> Self:
        self.pool_name = pool

        return self

    def capacity(self, capacity: int) -> Self:
        self.xml_model.capacity = lvstoragevol.capacity(value=capacity, unit="B")

        return self

    # Writes go to the volume, and reads of what wasn't written to the image (whose size it takes).
    def backing(self, image: str | Path) -> Self:
        self.xml_model.backing_store = lvstoragevol.backing_store(
            path=lvstoragevol.backing_store_path(value=str(Path(image).resolve())),
            format=lvstoragevol.format(type="qcow2"),
        )

        return self

    def get_name(self) -> str:
        return self.xml_model.name.value

    def get_pool(self) -> str:
        return self.pool_name
