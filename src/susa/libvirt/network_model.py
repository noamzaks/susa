from __future__ import annotations

import ipaddress

import pydantic_libvirt.network as lvnetwork
from typing_extensions import Self

from susa.libvirt.interface_model import InterfaceModel
from susa.libvirt.model import Model
from susa.utilities.generic import random_id


class NetworkModel(Model[lvnetwork.network]):
    xml_model_type = lvnetwork.network

    def __init__(
        self, name: str | None = None, xml_model: lvnetwork.network | None = None
    ) -> None:
        self.xml_model = xml_model or lvnetwork.network(
            name=lvnetwork.name(value=name or f"susa-{random_id(10)}"),
            ip_list=[],
        )

    def get_name(self) -> str:
        return self.xml_model.name.value

    def get_hosts(self) -> dict[str, str]:
        """The IPs reserved for MACs by the DHCP server of the network's first IP, keyed by MAC."""
        ip_list = self.xml_model.ip_list or []
        dhcp = ip_list[0].dhcp if len(ip_list) > 0 else None
        if dhcp is None:
            return {}

        return {h.mac: h.ip for h in dhcp.host_list or [] if h.mac is not None}

    def get_ip(self, mac: str) -> str | None:
        """The IP reserved for `mac`, if any."""
        return self.get_hosts().get(mac)

    def ip(
        self, address: str, netmask: str = "255.255.255.0", dhcp: bool = True
    ) -> Self:
        assert self.xml_model.ip_list is not None

        ip = lvnetwork.ip(address=address, netmask=netmask)

        if dhcp:
            network = ipaddress.IPv4Network(f"{address}/{netmask}", strict=False)
            gateway = ipaddress.IPv4Address(address)
            first_host = network.network_address + 1
            last_host = network.broadcast_address - 1

            range_list = []
            if first_host <= gateway - 1:
                range_list.append(
                    lvnetwork.range(start=str(first_host), end=str(gateway - 1))
                )
            if gateway + 1 <= last_host:
                range_list.append(
                    lvnetwork.range(start=str(gateway + 1), end=str(last_host))
                )

            ip.dhcp = lvnetwork.dhcp(range_list=range_list)

        self.xml_model.ip_list.append(ip)

        return self

    def nat(self) -> Self:
        self.xml_model.forward = lvnetwork.forward(mode="nat")

        return self

    def default_bridge(self) -> Self:
        self.xml_model.bridge = lvnetwork.bridge(
            name=self.xml_model.name.value,
            stp="off",
            delay=0,
        )

        return self

    def default(self) -> Self:
        return self.default_bridge()

    def interface(self, interface: InterfaceModel, ip: str | None = None) -> Self:
        interface.network(self.get_name())

        ip_list = self.xml_model.ip_list or []
        dhcp = ip_list[0].dhcp if len(ip_list) > 0 else None
        if dhcp is None:
            assert ip is None, (
                "Cannot set the IP of an interface before adding some IP with DHCP to the network!"
            )
            return self

        assert interface.xml_model.mac is not None
        if dhcp.host_list is None:
            dhcp.host_list = []

        if ip is None:
            used = {ipaddress.ip_address(host.ip) for host in dhcp.host_list}
            candidates = (
                ipaddress.ip_address(n)
                for r in dhcp.range_list or []
                for n in range(
                    int(ipaddress.ip_address(r.start)),
                    int(ipaddress.ip_address(r.end)) + 1,
                )
            )
            ip = next((str(c) for c in candidates if c not in used), None)
            if ip is None:
                raise RuntimeError(
                    f"No free IP left in the DHCP ranges of {self.xml_model.name.value}"
                )

        dhcp.host_list.append(
            lvnetwork.dhcp_host(mac=interface.xml_model.mac.address, ip=ip)
        )

        return self
