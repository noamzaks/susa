from __future__ import annotations

import json

from typing_extensions import Self, override

from susa.kubevirt._kubectl import Manifest, random_name
from susa.kubevirt.model import KVModel


class KVNetworkModel(KVModel):
    def __init__(self, name: str | None = None) -> None:
        name = name or random_name()
        self.manifest = self._definition(name, name, {})
        self.host_ip: str | None = None
        self.prefix_length = 24

    @override
    def name(self, name: str) -> Self:
        config = json.loads(self.manifest["spec"]["config"])
        config["name"] = config["bridge"] = name
        self.manifest["spec"]["config"] = json.dumps(config)

        return super().name(name)

    # The node's address on the network, through which it reaches the machines.
    def ip(self, ip: str, prefix: int = 24) -> Self:
        self.host_ip = ip
        self.prefix_length = prefix

        return self

    # A definition of the same bridge, whose only address KubeVirt gives the guest over DHCP.
    def attachment(self, name: str, ip: str) -> Manifest:
        address = {"address": f"{ip}/{self.prefix_length}"}
        if self.host_ip is not None:
            address["gateway"] = self.host_ip
        ipam: Manifest = {"type": "static", "addresses": [address]}
        return self._definition(
            name, self.get_name(), ipam, is_gateway=self.host_ip is not None
        )

    def _definition(
        self, name: str, bridge: str, ipam: Manifest, is_gateway: bool = False
    ) -> Manifest:
        config = {
            "cniVersion": "0.3.1",
            "name": name,
            "type": "bridge",
            "bridge": bridge,
            "isGateway": is_gateway,
            "ipam": ipam,
        }
        return {
            "apiVersion": "k8s.cni.cncf.io/v1",
            "kind": "NetworkAttachmentDefinition",
            "metadata": {"name": name},
            "spec": {"config": json.dumps(config)},
        }
