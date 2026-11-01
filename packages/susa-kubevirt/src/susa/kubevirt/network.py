from __future__ import annotations

import json
import shlex
from typing import Any

from typing_extensions import override

from susa.core.interface import BasicInterface, Interface
from susa.core.network import CommandSniffer, Network, Sniffable
from susa.kubevirt._kubectl import create, delete, kubectl
from susa.kubevirt.network_model import KVNetworkModel
from susa.kubevirt.node_pod import KVNodePod


class KVNetwork(Network, Sniffable):
    def __init__(self, model: KVNetworkModel, timeout: float = 300) -> None:
        self.model = model
        self.timeout = timeout

    @property
    @override
    def name(self) -> str:
        return self.model.get_name()

    @property
    @override
    def interfaces(self) -> list[Interface]:
        ips: dict[str, str | None] = {}
        for attachment in self._items("network-attachment-definitions"):
            config = json.loads(attachment["spec"]["config"])
            if config.get("bridge") == self.name:
                addresses = config["ipam"].get("addresses", [{"address": ""}])
                ips[attachment["metadata"]["name"]] = (
                    addresses[0]["address"].split("/")[0] or None
                )
        result: list[Interface] = []
        for machine in self._items("vmi"):
            networks = {
                network["name"]: network["multus"]["networkName"]
                for network in machine["spec"]["networks"]
                if "multus" in network
            }
            for interface in machine["status"].get("interfaces", []):
                attachment = networks.get(interface.get("name"))
                if attachment in ips:
                    result.append(BasicInterface(interface["mac"], ips[attachment]))
        return result

    # CNI would make the bridge only for the first machine, and never remove it.
    @override
    def create(self) -> None:
        with KVNodePod(self.timeout) as pod:
            pod.wait_until_ready()
            # Another bridge with this address (e.g. of a killed run) would take the route to the machines.
            ip = self.model.host_ip
            if ip is not None and f" {ip}/" in pod.run("ip", "-o", "address"):
                raise RuntimeError(f"{ip} is already on the node")
            pod.run("ip", "link", "add", self.name, "type", "bridge")
            pod.run("ip", "link", "set", self.name, "up")
        create(self.model.manifest)

    @override
    def destroy(self) -> None:
        delete("network-attachment-definition", self.name, self.timeout)
        with KVNodePod(self.timeout) as pod:
            pod.wait_until_ready()
            pod.run("ip", "link", "del", self.name)

    @override
    def sniffer(self) -> KVSniffer:
        return KVSniffer(self.name, self.timeout)

    def _items(self, resource: str) -> list[Any]:
        items: list[Any] = json.loads(kubectl("get", resource, "-o=json"))["items"]
        return items


class KVSniffer(CommandSniffer):
    def __init__(self, bridge: str, timeout: float = 300) -> None:
        self.pod = KVNodePod(timeout)
        command = ["kubectl", "exec", self.pod.name, "--"]
        super().__init__(
            shlex.join([*command, "tcpdump", "-i", bridge, "-U", "-w", "-"])
        )

    @override
    def create(self) -> None:
        self.pod.create()
        try:
            self.pod.wait_until_ready()
            super().create()
        except BaseException:
            self.pod.destroy()
            raise

    @override
    def destroy(self) -> None:
        super().destroy()
        self.pod.destroy()
