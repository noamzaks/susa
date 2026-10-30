from __future__ import annotations

import shlex
import time

from typing_extensions import override

import libvirt as lv
from susa.core.communicator import HOST, AsyncCommand, AsyncCommandRunner
from susa.core.interface import BasicInterface, Interface
from susa.core.network import Network, Sniffable, Sniffer
from susa.libvirt.entity import LVEntity
from susa.libvirt.network_model import NetworkModel


class LVNetwork(LVEntity[lv.virNetwork, NetworkModel], Network, Sniffable):
    def __init__(self, model: NetworkModel) -> None:
        super().__init__(model)

    @property
    @override
    def name(self) -> str:
        return self.model.get_name()

    @property
    @override
    def interfaces(self) -> list[Interface]:
        # libvirt doesn't record which interfaces are connected to a network, only the IPs reserved for them.
        return [BasicInterface(m, ip) for m, ip in self.model.get_hosts().items()]

    @override
    def create(self) -> None:
        assert self.value is None
        self.value = self.conn.networkCreateXML(self.xml())

    @override
    def destroy(self) -> None:
        assert self.value is not None
        self.value.destroy()
        self.value = None

    @override
    def lookup(self) -> lv.virNetwork:
        return self.conn.networkLookupByName(self.name)

    @override
    def sniffer(self) -> LVSniffer:
        assert self.value is not None
        return LVSniffer(self.value.bridgeName())


class LVSniffer(Sniffer):
    CAPTURE_DRAIN_TIME = 1

    def __init__(self, interface: str, host: AsyncCommandRunner | None = None) -> None:
        self.interface = interface
        self.host = host or HOST.get()
        self.command: AsyncCommand | None = None

    @override
    def create(self) -> None:
        self.command = self.host.start(
            f"tcpdump -i {shlex.quote(self.interface)} -U -w -"
        )
        # tcpdump writes the pcap header once capturing started, and opening the reader waits for it.
        _ = self.pcap

    @override
    def destroy(self) -> None:
        assert self.command is not None
        # Let packets that were just captured reach tcpdump.
        time.sleep(LVSniffer.CAPTURE_DRAIN_TIME)
        self.command.kill()
        self.command.wait()

    @override
    def read(self, size: int | None = None, timeout: float | None = 0) -> bytes:
        assert self.command is not None
        return self.command.stdout.read(size, timeout)
