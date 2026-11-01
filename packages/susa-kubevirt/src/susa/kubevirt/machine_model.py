from __future__ import annotations

import json

from typing_extensions import Self

from susa.kubevirt._kubectl import Manifest, random_name
from susa.kubevirt.emulation import EMULATIONS, cross_architecture_script
from susa.kubevirt.model import KVModel
from susa.kubevirt.network_model import KVNetworkModel
from susa.kubevirt.volume_model import KVVolumeModel


class KVMachineModel(KVModel):
    SIDECAR_IMAGE = "quay.io/kubevirt/sidecar-shim:v1.9.1"

    def __init__(self, name: str | None = None) -> None:
        self.manifest = {
            "apiVersion": "kubevirt.io/v1",
            "kind": "VirtualMachine",
            "metadata": {"name": name or random_name()},
            "spec": {
                "runStrategy": "Always",
                "template": {
                    "metadata": {"annotations": {}},
                    "spec": {
                        "domain": {
                            "cpu": {"cores": 1},
                            "memory": {"guest": str(1 << 30)},
                            "devices": {"disks": [], "interfaces": []},
                        },
                        "networks": [],
                        "volumes": [],
                    },
                },
            },
        }
        self.ips: dict[str, str | None] = {}
        self.attachments: dict[str, Manifest] = {}
        self.hooks: dict[str, str] = {}
        self.sidecars: list[Manifest] = []

    def efi(self, secure_boot: bool = False) -> Self:
        efi = {"secureBoot": secure_boot}
        self._domain.setdefault("firmware", {})["bootloader"] = {"efi": efi}

        return self

    # From a container image, as the node's files aren't available to the machine.
    def kernel(
        self,
        image: str,
        kernel: str,
        initrd: str | None = None,
        cmdline: str | None = None,
    ) -> Self:
        container = {"image": image, "kernelPath": kernel}
        if initrd is not None:
            container["initrdPath"] = initrd
        boot: Manifest = {"container": container}
        if cmdline is not None:
            boot["kernelArgs"] = cmdline
        self._domain.setdefault("firmware", {})["kernelBoot"] = boot

        return self

    def memory(self, memory: int) -> Self:
        self._domain["memory"]["guest"] = str(memory)

        return self

    def cpu(self, cpu: int) -> Self:
        self._domain["cpu"]["cores"] = cpu

        return self

    # Runs QEMU for another architecture, in a virt-launcher image that has it (see scripts/kubevirt-launcher).
    def emulate(self, arch: str) -> Self:
        return self.hook(EMULATIONS[arch].script)

    # Through KubeVirt's cross-architecture support, which its CrossArchitectureVirtualization feature gate enables. Its name
    # for the architecture (e.g. amd64).
    def cross_architecture(self, architecture: str) -> Self:
        self._spec["architecture"] = architecture
        return self.hook(cross_architecture_script())

    # A script rewriting the domain as it's defined.
    def hook(self, script: str, image: str | None = None) -> Self:
        name = f"{self.get_name()}-hook{len(self.hooks)}"
        self.hooks[name] = script
        self.sidecars.append(
            {
                "args": ["--version", "v1alpha2"],
                "image": image or KVMachineModel.SIDECAR_IMAGE,
                "configMap": {
                    "name": name,
                    "key": "hook.sh",
                    "hookPath": "/usr/bin/onDefineDomain",
                },
            }
        )

        return self.annotation(
            "hooks.kubevirt.io/hookSidecars", json.dumps(self.sidecars)
        )

    def annotation(self, name: str, value: str) -> Self:
        self.manifest["spec"]["template"]["metadata"]["annotations"][name] = value

        return self

    def disk(self, name: str, volume: Manifest) -> Self:
        self._domain["devices"]["disks"].append(
            {"name": name, "disk": {"bus": "virtio"}}
        )
        self._spec["volumes"].append({"name": name, **volume})

        return self

    def interface(
        self,
        name: str,
        network: Manifest,
        model: str | None = None,
        pci_address: str | None = None,
    ) -> Self:
        interface: Manifest = {"name": name, "bridge": {}}
        if model is not None:
            interface["model"] = model
        if pci_address is not None:
            interface["pciAddress"] = pci_address
        self._domain["devices"]["interfaces"].append(interface)
        self._spec["networks"].append({"name": name, **network})

        return self

    def volume(self, volume: KVVolumeModel) -> Self:
        name = f"disk{len(self._spec['volumes'])}"
        return self.disk(name, {"dataVolume": {"name": volume.get_name()}})

    # With an IP, the machine has its own NetworkAttachmentDefinition of the network.
    def network(
        self,
        network: KVNetworkModel,
        ip: str | None = None,
        model: str | None = None,
        pci_address: str | None = None,
    ) -> Self:
        name = f"net{len(self._spec['networks'])}"
        attachment = network.get_name()
        self.ips[name] = ip
        if ip is not None:
            attachment = f"{self.get_name()}-{name}"
            self.attachments[attachment] = network.attachment(attachment, ip)
        return self.interface(
            name, {"multus": {"networkName": attachment}}, model, pci_address
        )

    def get_ips(self) -> dict[str, str | None]:
        return self.ips

    def get_attachments(self) -> dict[str, Manifest]:
        return self.attachments

    def get_hooks(self) -> dict[str, str]:
        return self.hooks

    @property
    def _spec(self) -> Manifest:
        spec: Manifest = self.manifest["spec"]["template"]["spec"]
        return spec

    @property
    def _domain(self) -> Manifest:
        domain: Manifest = self._spec["domain"]
        return domain
