from __future__ import annotations

import pydantic_libvirt.domain as lvdomain
from typing_extensions import Self

from susa.libvirt.arch import ARCH_DEFAULTS
from susa.libvirt.model import Model
from susa.utilities.networking import random_mac

QEMU_MAC_PREFIX = "52:54:00"


class InterfaceModel(Model[lvdomain.devices_interface]):
    xml_model_type = lvdomain.devices_interface

    def __init__(
        self,
        xml_model: lvdomain.devices_interface | None = None,
        mac: str | None = None,
    ) -> None:
        self.xml_model = xml_model or lvdomain.devices_interface(
            type="network",
            mac=lvdomain.mac(address=mac or random_mac(prefix=QEMU_MAC_PREFIX)),
        )

    def mac(self, address: str) -> Self:
        self.xml_model.mac = lvdomain.mac(address=address)

        return self

    def network(self, name: str) -> Self:
        self.xml_model.source = lvdomain.interface_source(network=name)

        return self

    def default_model(self, arch: str) -> Self:
        self.xml_model.model = lvdomain.interface_options_model(
            type=ARCH_DEFAULTS[arch].nic
        )

        return self

    def default(self, arch: str) -> Self:
        return self.default_model(arch=arch)

    def get_mac(self) -> str:
        assert self.xml_model.mac is not None

        return self.xml_model.mac.address

    def get_network(self) -> str | None:
        if self.xml_model.source is None:
            return None

        return self.xml_model.source.network
