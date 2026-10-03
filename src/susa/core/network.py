from __future__ import annotations

from abc import ABC, abstractmethod
from functools import cached_property
from typing import TYPE_CHECKING

from susa.core.interface import Interface
from susa.core.resource import Resource
from susa.core.stream import OutputStream

if TYPE_CHECKING:
    from scapy.packet import Packet
    from scapy.utils import PcapReader

SNIFFER_TIMEOUT = 60


class Network(Resource):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def interfaces(self) -> list[Interface]: ...


class Sniffer(Resource, OutputStream):
    @cached_property
    def pcap(self) -> PcapReader:
        from scapy.utils import PcapReader

        # scapy accepts file objects, but only annotates `str` where mypy looks.
        return PcapReader(self.file(SNIFFER_TIMEOUT))  # type: ignore

    def next_packet(self) -> Packet:
        return self.pcap.read_packet()

    def packets(self) -> list[Packet]:
        return list(self.pcap)


class Sniffable(ABC):
    @abstractmethod
    def sniffer(self) -> Sniffer: ...
