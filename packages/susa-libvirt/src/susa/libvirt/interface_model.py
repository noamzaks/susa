from __future__ import annotations

from typing_extensions import Self

from susa.libvirt.model import LVModel, child, node, put
from susa.utilities.networking import random_mac


class LVInterfaceModel(LVModel):
    QEMU_MAC_PREFIX = "52:54:00"

    def __init__(self, mac: str | None = None) -> None:
        address = mac or random_mac(prefix=LVInterfaceModel.QEMU_MAC_PREFIX)
        self.element = node(
            "interface",
            elements=[node("mac", attrs={"address": address})],
            attrs={"type": "network"},
        )

    def mac(self, address: str) -> Self:
        put(self.element, node("mac", attrs={"address": address}))

        return self

    def network(self, name: str) -> Self:
        put(self.element, node("source", attrs={"network": name}))

        return self

    def model(self, type: str) -> Self:
        put(self.element, node("model", attrs={"type": type}))

        return self

    def get_mac(self) -> str:
        return child(self.element, "mac").attrib["address"]

    def get_network(self) -> str | None:
        source = self.element.find("source")
        return None if source is None else source.get("network")
