from __future__ import annotations

from typing_extensions import Self

from susa.libvirt.model import Model, attribute, child, node, put
from susa.utilities.networking import random_mac


class InterfaceModel(Model):
    QEMU_MAC_PREFIX = "52:54:00"

    def __init__(self, mac: str | None = None) -> None:
        address = mac or random_mac(prefix=InterfaceModel.QEMU_MAC_PREFIX)
        self.element = node("interface", None, node("mac", address=address))
        attribute(self.element, "type", "network")

    def mac(self, address: str) -> Self:
        put(self.element, node("mac", address=address))

        return self

    def network(self, name: str) -> Self:
        put(self.element, node("source", network=name))

        return self

    def model(self, type: str) -> Self:
        put(self.element, node("model", type=type))

        return self

    def get_mac(self) -> str:
        return child(self.element, "mac").attrib["address"]

    def get_network(self) -> str | None:
        source = self.element.find("source")
        return None if source is None else source.get("network")
