from __future__ import annotations

import copy
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar

from typing_extensions import Self

from susa.libvirt.arch import ARCH_DEFAULTS, ArchDefaults, have_kvm
from susa.libvirt.disk_model import DiskModel
from susa.libvirt.interface_model import InterfaceModel
from susa.libvirt.model import Model, add, attribute, child, node, put
from susa.libvirt.network_model import NetworkModel
from susa.libvirt.volume_model import VolumeModel
from susa.utilities.generic import random_id

QEMU = "http://libvirt.org/schemas/domain/qemu/1.0"
ET.register_namespace("qemu", QEMU)


class MachineModel(Model):
    # The device names libvirt gives disks on each bus ("sd" for any other).
    BUS_PREFIXES: ClassVar[dict[str, str]] = {"ide": "hd", "fdc": "fd", "virtio": "vd"}

    def __init__(self, name: str | None = None) -> None:
        self.element = node(
            "domain",
            None,
            node("name", name or f"susa-{random_id(10)}"),
            node("devices"),
            type="qemu",
        )

    def name(self, name: str) -> Self:
        put(self.element, node("name", name))

        return self

    def arch(self, arch: str) -> Self:
        put(self.element, node("os", None, node("type", "hvm", arch=arch)))

        return self

    def machine(self, machine: str) -> Self:
        attribute(child(self.element, "os/type"), "machine", machine)

        return self

    def memory(self, memory: int) -> Self:
        put(self.element, node("memory", str(memory), unit="B"))

        return self

    def cpu(self, cpu: int) -> Self:
        put(self.element, node("vcpu", str(cpu)))

        return self

    def features(self, acpi: bool = False, gic: bool = False) -> Self:
        features = node("features")
        if acpi:
            add(features, node("acpi"))
        if gic:
            add(features, node("gic", version="3"))
        put(self.element, features)

        return self

    # libvirt picks the firmware by QEMU's firmware descriptors.
    def efi(self, secure_boot: bool = False) -> Self:
        os = child(self.element, "os")
        attribute(os, "firmware", "efi")
        enabled = "yes" if secure_boot else "no"
        feature = node("feature", enabled=enabled, name="secure-boot")
        put(os, node("firmware", None, feature))

        return self

    def kernel(
        self,
        kernel: str | Path,
        initrd: str | Path | None = None,
        cmdline: str | None = None,
    ) -> Self:
        os = child(self.element, "os")
        put(os, node("kernel", str(Path(kernel).resolve())))
        if initrd is not None:
            put(os, node("initrd", str(Path(initrd).resolve())))
        if cmdline is not None:
            put(os, node("cmdline", cmdline))

        return self

    def qemu_args(self, args: Sequence[str]) -> Self:
        tag = f"{{{QEMU}}}commandline"
        commandline = self.element.find(tag)
        if commandline is None:
            commandline = node(tag)
            add(self.element, commandline)
        for a in args:
            add(commandline, node(f"{{{QEMU}}}arg", value=a))

        return self

    def video(self, model: str) -> Self:
        add(self.get_devices(), node("video", None, node("model", type=model)))

        return self

    def vnc(self) -> Self:
        add(self.get_devices(), node("graphics", type="vnc", port="-1"))

        return self

    def tablet(self) -> Self:
        add(self.get_devices(), node("input", type="tablet", bus="usb"))

        return self

    def keyboard(self) -> Self:
        add(self.get_devices(), node("input", type="keyboard", bus="usb"))

        return self

    def usb(self) -> Self:
        usb = node("controller", index="0", type="usb")
        address = self.next_pci_address()
        if address is not None:
            add(usb, address)
        add(self.get_devices(), usb)

        return self

    def console(self) -> Self:
        add(self.get_devices(), node("console", type="pty"))

        return self

    def disk(self, disk: DiskModel) -> Self:
        bus = child(disk.element, "target").get("bus") or self.get_defaults().disk_bus
        target = node("target", dev=self.next_disk_name(bus))
        if bus is not None:
            attribute(target, "bus", bus)
        element = copy.deepcopy(disk.element)
        put(element, target)
        add(self.get_devices(), element)

        return self

    def interface(self, interface: InterfaceModel) -> Self:
        if interface.element.find("model") is None:
            interface.model(self.get_defaults().nic)
        if interface.element.find("address") is None:
            address = self.next_pci_address()
            if address is not None:
                add(interface.element, address)
        add(self.get_devices(), interface.element)

        return self

    def volume(self, volume: VolumeModel) -> Self:
        return self.disk(DiskModel().volume(volume))

    def network(self, network: NetworkModel, ip: str | None = None) -> Self:
        interface = InterfaceModel()
        network.interface(interface, ip)
        return self.interface(interface)

    def default_type(self) -> Self:
        attribute(self.element, "type", "kvm" if have_kvm(self.get_arch()) else "qemu")

        return self

    def default_cpu(self) -> Self:
        if self.element.get("type") == "kvm":
            put(self.element, node("cpu", mode="host-passthrough"))
        elif (mode := self.get_defaults().tcg_cpu) is not None:
            put(self.element, node("cpu", mode=mode))

        return self

    def default(self) -> Self:
        defaults = self.get_defaults()

        self.default_type().machine(defaults.machine).default_cpu()
        self.features(acpi=defaults.acpi, gic=defaults.gic)
        self.video(defaults.video).vnc().tablet().keyboard().usb().console()
        if defaults.qemu_args:
            self.qemu_args(defaults.qemu_args)

        return self

    def next_disk_name(self, bus: str | None) -> str:
        prefix = MachineModel.BUS_PREFIXES.get(bus, "sd") if bus is not None else "sd"
        suffix = ""
        index = len(self.get_devices().findall("disk")) + 1
        while index > 0:
            index, remainder = divmod(index - 1, 26)
            suffix = chr(ord("a") + remainder) + suffix
        return prefix + suffix

    def next_pci_address(self) -> ET.Element | None:
        slots = self.get_defaults().pci_slots
        if slots is None:
            return None

        devices = self.get_devices()
        addresses = [*devices.findall("interface/address")]
        addresses += devices.findall("controller/address")
        # libvirt writes them in hexadecimal.
        used = {int(a.attrib["slot"], 0) for a in addresses if "slot" in a.attrib}
        free = [slot for slot in slots if slot not in used]
        if not free:
            raise RuntimeError(f"There's no free PCI slot left (of {slots})")

        return node(
            "address", type="pci", domain="0", bus="0", slot=str(free[0]), function="0"
        )

    def get_name(self) -> str:
        name = child(self.element, "name").text
        assert name is not None
        return name

    def get_arch(self) -> str:
        return child(self.element, "os/type").attrib["arch"]

    def get_defaults(self) -> ArchDefaults:
        return ARCH_DEFAULTS[self.get_arch()]

    def get_firmware(self) -> str | None:
        return child(self.element, "os").get("firmware")

    def get_devices(self) -> ET.Element:
        return child(self.element, "devices")

    def get_interfaces(self) -> list[InterfaceModel]:
        return [InterfaceModel.of(i) for i in self.get_devices().findall("interface")]


class SnapshotModel(Model):
    def __init__(self, name: str | None = None) -> None:
        self.element = node(
            "domainsnapshot", None, node("name", name or f"susa-{random_id(10)}")
        )

    def name(self, name: str) -> Self:
        put(self.element, node("name", name))

        return self

    def get_name(self) -> str:
        name = child(self.element, "name").text
        assert name is not None
        return name
