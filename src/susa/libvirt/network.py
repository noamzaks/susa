import libvirt as lv
from typing_extensions import override

from susa.core.interface import Interface
from susa.core.network import Network
from susa.libvirt.entity import LVEntity
from susa.libvirt.interface import LVInterface
from susa.libvirt.network_model import NetworkModel


class LVNetwork(LVEntity[lv.virNetwork, NetworkModel], Network):
    @property
    @override
    def name(self) -> str:
        return self.model.get_name()

    @property
    @override
    def interfaces(self) -> list[Interface]:
        # libvirt doesn't record which interfaces are connected to a network, only the IPs reserved for them.
        return [LVInterface(mac, ip) for mac, ip in self.model.get_hosts().items()]

    @override
    def create(self) -> None:
        assert self.value is None
        self.value = self.conn.networkCreateXML(self.build())

    @override
    def destroy(self) -> None:
        assert self.value is not None
        self.value.destroy()
        self.value = None
