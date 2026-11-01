from __future__ import annotations

from abc import ABC, abstractmethod
from functools import cached_property
from typing import TYPE_CHECKING

from typing_extensions import override

from susa.core.communicator import HOST, AsyncCommand, AsyncCommandRunner
from susa.core.interface import Interface
from susa.core.resource import Resource
from susa.core.stream import OutputStream

if TYPE_CHECKING:
    from scapy.packet import Packet
    from scapy.utils import PcapReader


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
        return PcapReader(self.file())  # type: ignore

    def next_packet(self) -> Packet:
        return self.pcap.read_packet()

    def packets(self) -> list[Packet]:
        return list(self.pcap)


# A command that writes the capture to its output.
class CommandSniffer(Sniffer):
    def __init__(self, command: str, host: AsyncCommandRunner | None = None) -> None:
        self.capture_command = command
        self.host = host or HOST.get()
        self.command: AsyncCommand | None = None

    @override
    def create(self) -> None:
        self.command = self.host.start(self.capture_command)

    @override
    def destroy(self) -> None:
        assert self.command is not None
        self.command.kill()
        self.command.wait()

    @override
    def read(self, size: int | None = None, timeout: float | None = 0) -> bytes:
        assert self.command is not None
        return self.command.stdout.read(size, timeout)


class Sniffable(ABC):
    @abstractmethod
    def sniffer(self) -> Sniffer: ...
