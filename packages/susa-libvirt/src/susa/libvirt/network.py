from __future__ import annotations

import re
import shlex

from typing_extensions import override

from susa.core.communicator import AsyncCommandRunner
from susa.core.interface import BasicInterface, Interface
from susa.core.network import CommandSniffer, Network, Sniffable
from susa.libvirt._virsh import virsh, virsh_guarded, virsh_xml
from susa.libvirt.entity import LVEntity
from susa.libvirt.network_model import LVNetworkModel


class LVNetwork(LVEntity[LVNetworkModel], Network, Sniffable):
    def __init__(self, model: LVNetworkModel) -> None:
        super().__init__(model)

    @property
    @override
    def name(self) -> str:
        return self.model.get_name()

    @property
    @override
    def interfaces(self) -> list[Interface]:
        return [BasicInterface(m, ip) for m, ip in self.model.get_hosts().items()]

    @override
    def create(self) -> None:
        with virsh_guarded(["net-destroy", self.name]) as self.guard:
            virsh_xml(self._xml(), "net-create")

    @override
    def destroy(self) -> None:
        virsh("net-destroy", self.name)
        self.guard.cancel()

    @override
    def sniffer(self) -> LVSniffer:
        match = re.search(
            r"^Bridge:\s+(\S+)", virsh("net-info", self.name), re.MULTILINE
        )
        assert match is not None
        return LVSniffer(match[1])


class LVSniffer(CommandSniffer):
    def __init__(self, interface: str, host: AsyncCommandRunner | None = None) -> None:
        super().__init__(f"tcpdump -i {shlex.quote(interface)} -U -w -", host)
