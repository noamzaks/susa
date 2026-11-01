from __future__ import annotations

import ipaddress

from typing_extensions import Self

from susa.libvirt.interface_model import LVInterfaceModel
from susa.libvirt.model import LVModel, add, child, node, put
from susa.utilities.generic import random_id


class LVNetworkModel(LVModel):
    def __init__(self, name: str | None = None) -> None:
        self.element = node(
            "network", elements=[node("name", text=name or f"susa-{random_id(10)}")]
        )

    def name(self, name: str) -> Self:
        put(self.element, node("name", text=name))

        return self

    def ip(
        self,
        address: str,
        netmask: str = "255.255.255.0",
        dhcp: bool = True,
    ) -> Self:
        ip = node("ip", attrs={"address": address, "netmask": netmask})
        if dhcp:
            network = ipaddress.IPv4Network(f"{address}/{netmask}", strict=False)
            own = ipaddress.IPv4Address(address)
            ranges = [
                (network.network_address + 1, own - 1),
                (own + 1, network.broadcast_address - 1),
            ]
            add(
                ip,
                node(
                    "dhcp",
                    elements=[
                        *(
                            node("range", attrs={"start": str(start), "end": str(end)})
                            for start, end in ranges
                            if start <= end
                        )
                    ],
                ),
            )
        put(self.element, ip)

        # Guests can resolve the host's address (which e.g. some rlogin servers require of clients).
        host = node(
            "host", elements=[node("hostname", text="host")], attrs={"ip": address}
        )
        put(self.element, node("dns", elements=[host]))

        return self

    def nat(self) -> Self:
        put(self.element, node("forward", attrs={"mode": "nat"}))

        return self

    def interface(self, interface: LVInterfaceModel, ip: str | None = None) -> Self:
        interface.network(self.get_name())
        dhcp = self.element.find("ip/dhcp")
        if dhcp is None:
            assert ip is None, "Add an IP with DHCP to the network first!"
            return self

        if ip is None:
            own = child(self.element, "ip").attrib
            used = {own["address"], *self.get_hosts().values()}
            network = ipaddress.IPv4Network(
                f"{own['address']}/{own['netmask']}", strict=False
            )
            ip = next((str(a) for a in network.hosts() if str(a) not in used), None)
            if ip is None:
                raise RuntimeError(f"There's no free IP left in {self.get_name()}")
        add(dhcp, node("host", attrs={"mac": interface.get_mac(), "ip": ip}))

        return self

    def default(self) -> Self:
        put(self.element, node("bridge", attrs={"stp": "off"}))

        return self

    def get_name(self) -> str:
        name = child(self.element, "name").text
        assert name is not None
        return name

    # The IPs reserved for MAC addresses.
    def get_hosts(self) -> dict[str, str | None]:
        hosts = self.element.findall("ip/dhcp/host")
        return {h.attrib["mac"]: h.get("ip") for h in hosts if "mac" in h.attrib}
