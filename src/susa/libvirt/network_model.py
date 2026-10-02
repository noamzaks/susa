from __future__ import annotations

import ipaddress

import pydantic_libvirt.network as lvnetwork
from typing_extensions import Self

from susa.libvirt.interface_model import InterfaceModel
from susa.libvirt.model import Model
from susa.utilities.generic import random_id
from susa.utilities.networking import reserve_subnet


class NetworkModel(Model[lvnetwork.network]):
    xml_model_type = lvnetwork.network

    def __init__(
        self, name: str | None = None, xml_model: lvnetwork.network | None = None
    ) -> None:
        self.xml_model = xml_model or lvnetwork.network(
            name=lvnetwork.name(value=name or f"susa-{random_id(10)}")
        )

    def name(self, name: str) -> Self:
        self.xml_model.name = lvnetwork.name(value=name)

        return self

    # Without an address, the first one of a free subnet (reserved for this process, see `reserve_subnet`).
    def ip(
        self,
        address: str | None = None,
        netmask: str = "255.255.255.0",
        dhcp: bool = True,
    ) -> Self:
        if address is None:
            prefix = ipaddress.IPv4Network(f"0.0.0.0/{netmask}").prefixlen
            address = str(next(reserve_subnet(prefix).hosts()))

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

        self.xml_model.ip_list = [*(self.xml_model.ip_list or []), ip]

        # Guests can resolve the host's address (which e.g. some rlogin servers require of clients).
        host = lvnetwork.dns_host(
            ip=address, hostname_list=[lvnetwork.hostname(value="host")]
        )
        dns = self.xml_model.dns = self.xml_model.dns or lvnetwork.dns()
        dns.host_list = [*(dns.host_list or []), host]

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
            used = {host.ip for host in hosts}
            free = (
                str(address)
                for r in dhcp.range_list or []
                for block in ipaddress.summarize_address_range(
                    ipaddress.IPv4Address(r.start), ipaddress.IPv4Address(r.end)
                )
                for address in block
                if str(address) not in used
            )
            ip = next(free, None)
            if ip is None:
                raise RuntimeError(f"There's no free IP left in {self.get_name()}")
        hosts.append(lvnetwork.dhcp_host(mac=interface.get_mac(), ip=ip))

        return self

    def default_bridge(self) -> Self:
        self.xml_model.bridge = lvnetwork.bridge(
            name=self.get_name(), stp="off", delay=0
        )

        return self

    def default(self) -> Self:
        return self.default_bridge()

    def get_name(self) -> str:
        return self.xml_model.name.value

    def get_dhcp(self) -> lvnetwork.dhcp | None:
        return self.xml_model.ip_list[0].dhcp if self.xml_model.ip_list else None

    def get_hosts(self) -> dict[str, str]:
        dhcp = self.get_dhcp()
        hosts = dhcp.host_list or [] if dhcp is not None else []
        return {host.mac: host.ip for host in hosts if host.mac is not None}

    def get_ip(self, mac: str) -> str | None:
        return self.get_hosts().get(mac)

    def get_bridge(self) -> str:
        assert (
            self.xml_model.bridge is not None and self.xml_model.bridge.name is not None
        )
        return self.xml_model.bridge.name
