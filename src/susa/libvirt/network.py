from __future__ import annotations

import os
import select
import subprocess
import time

import libvirt as lv
from typing_extensions import override

from susa.core.interface import BasicInterface, Interface
from susa.core.network import Network, Sniffable, Sniffer
from susa.libvirt.entity import LVEntity
from susa.libvirt.network_model import NetworkModel

CHUNK_SIZE = 1 << 16
CAPTURE_DRAIN_TIME = 1


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
        hosts = self.model.get_hosts() or []
        return [BasicInterface(h.mac, h.ip) for h in hosts if h.mac is not None]

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
    def __init__(self, interface: str) -> None:
        self.interface = interface
        self.process: subprocess.Popen[bytes] | None = None

    @override
    def create(self) -> None:
        self.process = subprocess.Popen(
            ["tcpdump", "-i", self.interface, "-U", "-w", "-"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        # tcpdump writes the pcap header once capturing started, and opening the reader waits for it.
        _ = self.pcap

    @override
    def destroy(self) -> None:
        assert self.process is not None
        # Let packets that were just captured reach tcpdump.
        time.sleep(CAPTURE_DRAIN_TIME)
        self.process.terminate()
        self.process.wait()

    @override
    def read(self, size: int | None = None, timeout: float | None = 0) -> bytes:
        assert self.process is not None and self.process.stdout is not None
        if not select.select([self.process.stdout], [], [], timeout)[0]:
            return b""
        data = os.read(self.process.stdout.fileno(), size or CHUNK_SIZE)
        if not data:
            raise EOFError
        return data
