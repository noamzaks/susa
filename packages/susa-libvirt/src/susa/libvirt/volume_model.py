from __future__ import annotations

from pathlib import Path

from typing_extensions import Self

from susa.libvirt.model import Model, child, node, put
from susa.utilities.generic import random_id


class VolumeModel(Model):
    def __init__(self, name: str | None = None) -> None:
        self.element = node(
            "volume",
            None,
            node("name", name or f"susa-{random_id(10)}"),
            node("target", None, node("format", type="qcow2")),
        )
        # The volume's XML doesn't say which pool it's in.
        self.pool_name = "default"

    def name(self, name: str) -> Self:
        put(self.element, node("name", name))

        return self

    def pool(self, pool: str) -> Self:
        self.pool_name = pool

        return self

    def capacity(self, capacity: int) -> Self:
        put(self.element, node("capacity", str(capacity), unit="B"))

        return self

    def backing(self, image: str | Path) -> Self:
        put(
            self.element,
            node(
                "backingStore",
                None,
                node("path", str(Path(image).resolve())),
                node("format", type="qcow2"),
            ),
        )

        return self

    def get_name(self) -> str:
        name = child(self.element, "name").text
        assert name is not None
        return name

    def get_pool(self) -> str:
        return self.pool_name
