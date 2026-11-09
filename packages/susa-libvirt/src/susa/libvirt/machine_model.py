from __future__ import annotations

import copy
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar

from typing_extensions import Self, override

from susa.libvirt.arch import ARCH_DEFAULTS, ArchDefaults, have_kvm
from susa.libvirt.disk_model import LVDiskModel
from susa.libvirt.interface_model import LVInterfaceModel
from susa.libvirt.model import LVModel, add, attribute, child, node, put
from susa.libvirt.network_model import LVNetworkModel
from susa.libvirt.volume_model import LVVolumeModel
from susa.utilities.generic import random_id


class LVMachineModel(LVModel):
    QEMU_NAMESPACE = "http://libvirt.org/schemas/domain/qemu/1.0"
    BUS_PREFIXES: ClassVar[dict[str, str]] = {"ide": "hd", "fdc": "fd", "virtio": "vd"}

    def __init__(self, name: str | None = None) -> None:
        self.element = node(
            "domain",
            elements=[
                node("name", text=name or f"susa-{random_id(10)}"),
                node("devices"),
            ],
            attrs={"type": "qemu"},
        )

    def name(self, name: str) -> Self:
        put(self.element, node("name", text=name))

        return self

    def arch(self, arch: str) -> Self:
        put(
            self.element,
            node("os", elements=[node("type", attrs={"arch": arch}, text="hvm")]),
        )

        return self

    def machine(self, machine: str) -> Self:
        attribute(child(self.element, "os/type"), "machine", machine)

        return self

    def memory(self, memory: int) -> Self:
        put(self.element, node("memory", attrs={"unit": "B"}, text=str(memory)))

        return self

    def cpu(self, cpu: int) -> Self:
        put(self.element, node("vcpu", text=str(cpu)))

        return self

    def features(self, acpi: bool = False, gic: bool = False) -> Self:
        features = node("features")
        if acpi:
            add(features, node("acpi"))
        if gic:
            add(features, node("gic", attrs={"version": "3"}))
        put(self.element, features)

        return self

    def efi(self, secure_boot: bool = False) -> Self:
        os = child(self.element, "os")
        attribute(os, "firmware", "efi")
        enabled = "yes" if secure_boot else "no"
        feature = node("feature", attrs={"enabled": enabled, "name": "secure-boot"})
        put(os, node("firmware", elements=[feature]))

        return self

    def kernel(
        self,
        kernel: str | Path,
        initrd: str | Path | None = None,
        cmdline: str | None = None,
    ) -> Self:
        os = child(self.element, "os")
        put(os, node("kernel", text=str(Path(kernel).resolve())))
        if initrd is not None:
            put(os, node("initrd", text=str(Path(initrd).resolve())))
        if cmdline is not None:
            put(os, node("cmdline", text=cmdline))

        return self

    def qemu_args(self, args: Sequence[str]) -> Self:
        commandline = next(
            (other for other in self.element if other.tag == "qemu:commandline"), None
        )
        if commandline is None:
            commandline = node("qemu:commandline")
            add(self.element, commandline)
            attribute(self.element, "xmlns:qemu", LVMachineModel.QEMU_NAMESPACE)
        for a in args:
            add(commandline, node("qemu:arg", attrs={"value": a}))

        return self

    def video(self, model: str) -> Self:
        add(
            self._devices,
            node("video", elements=[node("model", attrs={"type": model})]),
        )

        return self

    def vnc(self) -> Self:
        add(self._devices, node("graphics", attrs={"type": "vnc", "port": "-1"}))

        return self

    def tablet(self) -> Self:
        add(self._devices, node("input", attrs={"type": "tablet", "bus": "usb"}))

        return self

    def keyboard(self) -> Self:
        add(self._devices, node("input", attrs={"type": "keyboard", "bus": "usb"}))

        return self

    def usb(self) -> Self:
        usb = node("controller", attrs={"index": "0", "type": "usb"})
        address = self._next_pci_address()
        if address is not None:
            add(usb, address)
        add(self._devices, usb)

        return self

    def console(self) -> Self:
        add(self._devices, node("console", attrs={"type": "pty"}))

        return self

    def disk(self, disk: LVDiskModel) -> Self:
        element = copy.deepcopy(disk.element)
        target = element.find("target")
        bus = self._defaults.disk_bus if target is None else target.attrib["bus"]
        put(
            element,
            node("target", attrs={"bus": bus, "dev": self._next_disk_name(bus)}),
        )
        add(self._devices, element)

        return self

    def interface(self, interface: LVInterfaceModel) -> Self:
        if interface.element.find("model") is None:
            interface.model(self._defaults.nic)
        if interface.element.find("address") is None:
            address = self._next_pci_address()
            if address is not None:
                add(interface.element, address)
        add(self._devices, interface.element)

        return self

    def volume(self, volume: LVVolumeModel) -> Self:
        return self.disk(LVDiskModel().volume(volume))

    def network(self, network: LVNetworkModel, ip: str | None = None) -> Self:
        interface = LVInterfaceModel()
        network.interface(interface, ip)
        return self.interface(interface)

    def default_type(self) -> Self:
        attribute(self.element, "type", "kvm" if have_kvm(self.get_arch()) else "qemu")

        return self

    def default_cpu(self) -> Self:
        if self.element.get("type") == "kvm":
            put(self.element, node("cpu", attrs={"mode": "host-passthrough"}))
        elif (mode := self._defaults.tcg_cpu) is not None:
            put(self.element, node("cpu", attrs={"mode": mode}))

        return self

    def default_machine(self) -> Self:
        return self.machine(self._defaults.machine)

    def default_features(self) -> Self:
        defaults = self._defaults
        return self.features(acpi=defaults.acpi, gic=defaults.gic)

    def default_video(self) -> Self:
        return self.video(self._defaults.video)

    def default_qemu_args(self) -> Self:
        if args := self._defaults.qemu_args:
            self.qemu_args(args)

        return self

    def default(self) -> Self:
        return (
            self.default_type()
            .default_machine()
            .default_cpu()
            .default_features()
            .default_video()
            .vnc()
            .tablet()
            .keyboard()
            .usb()
            .console()
            .default_qemu_args()
        )

    @classmethod
    @override
    def parse(cls, xml: str | bytes) -> Self:
        model = super().parse(xml)
        namespace = f"{{{LVMachineModel.QEMU_NAMESPACE}}}"
        for element in model.element.iter():
            if element.tag.startswith(namespace):
                element.tag = element.tag.replace(namespace, "qemu:")
                attribute(model.element, "xmlns:qemu", LVMachineModel.QEMU_NAMESPACE)
        return model

    def get_name(self) -> str:
        name = child(self.element, "name").text
        assert name is not None
        return name

    def get_arch(self) -> str:
        return child(self.element, "os/type").attrib["arch"]

    def get_firmware(self) -> str | None:
        return child(self.element, "os").get("firmware")

    def get_interfaces(self) -> list[LVInterfaceModel]:
        return [LVInterfaceModel.of(i) for i in self._devices.findall("interface")]

    @property
    def _defaults(self) -> ArchDefaults:
        return ARCH_DEFAULTS[self.get_arch()]

    @property
    def _devices(self) -> ET.Element:
        return child(self.element, "devices")

    def _next_disk_name(self, bus: str) -> str:
        prefix = LVMachineModel.BUS_PREFIXES.get(bus, "sd")
        suffix = ""
        index = len(self._devices.findall("disk")) + 1
        while index > 0:
            index, remainder = divmod(index - 1, 26)
            suffix = chr(ord("a") + remainder) + suffix
        return prefix + suffix

    def _next_pci_address(self) -> ET.Element | None:
        slots = self._defaults.pci_slots
        if slots is None:
            return None

        devices = self._devices
        addresses = [*devices.findall("interface/address")]
        addresses += devices.findall("controller/address")
        used = {int(a.attrib["slot"], 0) for a in addresses if "slot" in a.attrib}
        free = [slot for slot in slots if slot not in used]
        if not free:
            raise RuntimeError(f"There's no free PCI slot left (of {slots})")

        return node(
            "address",
            attrs={
                "type": "pci",
                "domain": "0",
                "bus": "0",
                "slot": str(free[0]),
                "function": "0",
            },
        )


class LVSnapshotModel(LVModel):
    def __init__(self, name: str | None = None) -> None:
        self.element = node(
            "domainsnapshot",
            elements=[node("name", text=name or f"susa-{random_id(10)}")],
        )

    def name(self, name: str) -> Self:
        put(self.element, node("name", text=name))

        return self

    def get_name(self) -> str:
        name = child(self.element, "name").text
        assert name is not None
        return name
