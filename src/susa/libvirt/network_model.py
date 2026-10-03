from __future__ import annotations

import ipaddress

import pydantic_libvirt.network as lvnetwork
from typing_extensions import Self

from susa.libvirt.interface_model import InterfaceModel
from susa.libvirt.model import Model
from susa.utilities.generic import random_id
from susa.utilities.networking import free_subnet


class NetworkModel(Model[lvnetwork.network]):
    def __init__(
        self, name: str | None = None, xml_model: lvnetwork.network | None = None
    ) -> None:
        self.xml_model = xml_model or lvnetwork.network(
            name=lvnetwork.name(value=name or f"susa-{random_id(10)}")
        )

    def name(self, name: str) -> Self:
        self.xml_model.name = lvnetwork.name(value=name)

        return self

    def ip(
        self,
        address: str | None = None,
        netmask: str = "255.255.255.0",
        dhcp: bool = True,
    ) -> Self:
        if address is None:
            address = str(next(free_subnet().hosts()))

        ip = lvnetwork.ip(address=address, netmask=netmask)
        if dhcp:
            # Every host address but the network's own.
            network = ipaddress.IPv4Network(f"{address}/{netmask}", strict=False)
            own = ipaddress.IPv4Address(address)
            ranges = [
                (network.network_address + 1, own - 1),
                (own + 1, network.broadcast_address - 1),
            ]
            ip.dhcp = lvnetwork.dhcp(
                range_list=[
                    lvnetwork.range(start=str(start), end=str(end))
                    for start, end in ranges
                    if start <= end
                ]
            )
        self.xml_model.ip_list = [ip]

        # Guests can resolve the host's address (which e.g. some rlogin servers require of clients).
        host = lvnetwork.dns_host(
            ip=address, hostname_list=[lvnetwork.hostname(value="host")]
        )
        self.xml_model.dns = lvnetwork.dns(host_list=[host])

        return self

    def nat(self) -> Self:
        self.xml_model.forward = lvnetwork.forward(mode="nat")

        return self

    def interface(self, interface: InterfaceModel, ip: str | None = None) -> Self:
        interface.network(self.get_name())
        dhcp = self.get_dhcp()
        if dhcp is None:
            assert ip is None, "Add an IP with DHCP to the network first!"
            return self

        hosts = dhcp.host_list = dhcp.host_list or []
        if ip is None:
            [own] = self.xml_model.ip_list or []
            used = {own.address, *(host.ip for host in hosts)}
            network = ipaddress.IPv4Network(
                f"{own.address}/{own.netmask}", strict=False
            )
            ip = next((str(a) for a in network.hosts() if str(a) not in used), None)
            if ip is None:
                raise RuntimeError(f"There's no free IP left in {self.get_name()}")
        hosts.append(lvnetwork.dhcp_host(mac=interface.get_mac(), ip=ip))

        return self

    # A bridge (which libvirt names) without the spanning tree protocol's delays.
    def default(self) -> Self:
        self.xml_model.bridge = lvnetwork.bridge(stp="off")

        return self

    def get_name(self) -> str:
        return self.xml_model.name.value

    def get_dhcp(self) -> lvnetwork.dhcp | None:
        return self.xml_model.ip_list[0].dhcp if self.xml_model.ip_list else None

    def get_hosts(self) -> list[lvnetwork.dhcp_host] | None:
        dhcp = self.get_dhcp()
        return None if dhcp is None else dhcp.host_list
