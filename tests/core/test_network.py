from __future__ import annotations

from io import BytesIO

from scapy.layers.inet import ICMP, IP
from scapy.layers.l2 import Ether
from scapy.utils import PcapWriter
from typing_extensions import override

from susa.core.network import Sniffer


class FakeSniffer(Sniffer):
    def __init__(self, data: bytes, chunk: int) -> None:
        self.chunks = [data[i : i + chunk] for i in range(0, len(data), chunk)]

    @override
    def create(self) -> None: ...

    @override
    def destroy(self) -> None: ...

    @override
    def read(self, size: int | None = None, timeout: float = 0) -> bytes:
        if not self.chunks:
            raise EOFError
        return self.chunks.pop(0)


def test_packets() -> None:
    sent = [Ether() / IP(dst=f"10.0.0.{i}") / ICMP() for i in range(3)]
    pcap = BytesIO()
    writer = PcapWriter(pcap)
    writer.write(sent)
    writer.flush()

    sniffer = FakeSniffer(pcap.getvalue(), 7)
    assert sniffer.next_packet()[IP].dst == "10.0.0.0"
    assert [p[IP].dst for p in sniffer.packets()] == ["10.0.0.1", "10.0.0.2"]
