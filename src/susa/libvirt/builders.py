import ipaddress
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Self, cast

import pydantic_libvirt.domain as lvdomain
import pydantic_libvirt.domainsnapshot as lvdomainsnapshot
import pydantic_libvirt.network as lvnetwork
import pydantic_xml

from susa.utilities import host_arch, random_id

QEMU_NAMESPACE = "http://libvirt.org/schemas/domain/qemu/1.0"

ET.register_namespace("qemu", QEMU_NAMESPACE)


def have_kvm(arch: str) -> bool:
    return arch == host_arch() and Path("/dev/kvm").exists()


@dataclass(frozen=True)
class ArchDefaults:
    machine: str
    pcie: bool = True
    acpi: bool = True
    apic: bool = False
    console_target: str = "serial"
    disk_bus: str | None = None
    video: str = "virtio"
    # If set, the only PCI slots that get an interrupt (libvirt would pick others).
    pci_slots: tuple[int, ...] | None = None
    gic: bool = False
    usb_model: str | None = None
    # The CPU mode to use when emulating (host's own architecture isn't available).
    tcg_cpu: str | None = None
    # Extra QEMU arguments libvirt has no XML for.
    qemu_args: tuple[str, ...] = ()
    nic: str = "e1000"


ARCH_DEFAULTS: dict[str, ArchDefaults] = {
    "x86_64": ArchDefaults("q35", apic=True, disk_bus="sata"),
    "aarch64": ArchDefaults(
        "virt",
        disk_bus="virtio",
        gic=True,
        usb_model="qemu-xhci",
        tcg_cpu="maximum",
        nic="virtio",
    ),
    "mips": ArchDefaults(
        "malta",
        pcie=False,
        acpi=False,
        disk_bus="ide",
        video="cirrus",
        pci_slots=(11, 12),
    ),
    "ppc64le": ArchDefaults(
        "pseries", pcie=False, acpi=False, disk_bus="virtio", video="vga"
    ),
    # vexpress-a9 has no usable display, so use virt (without highmem, which 32-bit
    # guests can't handle).
    "armv7l": ArchDefaults(
        "virt",
        acpi=False,
        disk_bus="virtio",
        usb_model="qemu-xhci",
        qemu_args=("-machine", "virt,highmem=off"),
    ),
    "riscv64": ArchDefaults(
        "virt", disk_bus="virtio", usb_model="qemu-xhci", nic="virtio"
    ),
}


class Builder[T: pydantic_xml.BaseXmlModel](ABC):
    xml_model: T
    xml_model_type: ClassVar[type[pydantic_xml.BaseXmlModel]]

    @abstractmethod
    def __init__(self, xml_model: T | None = None) -> None: ...

    def tree(self) -> ET.Element:
        return self.xml_model.to_xml_tree(exclude_none=True)

    def build(self) -> str:
        tree = self.tree()
        ET.indent(tree)
        return ET.tostring(tree, encoding="unicode")

    @classmethod
    def parse(cls, xml: str | bytes) -> Self:
        return cls(xml_model=cast(T, cls.xml_model_type.from_xml(xml)))


class DiskBuilder(Builder[lvdomain.disk]):
    xml_model_type = lvdomain.disk

    def __init__(self, xml_model: lvdomain.disk | None = None) -> None:
        self.xml_model = xml_model or lvdomain.disk(
            type="file",
            device="disk",
            # Overridden when added to a `DomainBuilder`.
            target=lvdomain.disk_target(dev="sda"),
        )

    def source(self, p: str | Path, format: str = "qcow2") -> Self:
        self.xml_model.driver = lvdomain.disk_driver(
            name="qemu", type=cast(Any, format)
        )
        self.xml_model.source = lvdomain.devices_disk_source(
            file=str(Path(p).resolve())
        )

        return self


class NetworkBuilder(Builder[lvnetwork.network]):
    xml_model_type = lvnetwork.network

    def __init__(
        self, name: str | None = None, xml_model: lvnetwork.network | None = None
    ) -> None:
        self.xml_model = xml_model or lvnetwork.network(
            name=lvnetwork.name(value=name or f"susa-{random_id(10)}"),
            ip_list=[],
        )

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


class InterfaceBuilder(Builder[lvdomain.devices_interface]):
    xml_model_type = lvdomain.devices_interface

    def __init__(self, xml_model: lvdomain.devices_interface | None = None) -> None:
        self.xml_model = xml_model or lvdomain.devices_interface(
            type="network",
        )

    def default_model(self) -> Self:
        self.xml_model.model = lvdomain.interface_options_model(type="e1000")

        return self

    def default(self) -> Self:
        return self.default_model()


class DomainBuilder(Builder[lvdomain.domain]):
    xml_model_type = lvdomain.domain

    def __init__(
        self, name: str | None = None, xml_model: lvdomain.domain | None = None
    ) -> None:
        self.xml_model = xml_model or lvdomain.domain(
            type="qemu",
            name=lvdomain.name(value=name or f"susa-{random_id(10)}"),
            devices=lvdomain.devices(
                video_list=[],
                graphics_list=[],
                input_list=[],
                controller_list=[],
                console_list=[],
                disk_list=[],
                interface_list=[],
            ),
        )

    def tree(self) -> ET.Element:
        tree = super().tree()

        # `pydantic_libvirt` doesn't know about the QEMU namespace.
        if (commandline := tree.find("commandline")) is not None:
            commandline.tag = f"{{{QEMU_NAMESPACE}}}commandline"
            for arg in commandline:
                arg.tag = f"{{{QEMU_NAMESPACE}}}{arg.tag}"

        return tree

    def arch(self, arch: str) -> Self:
        self.xml_model.os = lvdomain.os(
            type=lvdomain.os_type(
                value="hvm",
                arch=cast(Any, arch),
            ),
        )

        return self

    def memory(self, memory: int) -> Self:
        self.xml_model.memory = lvdomain.resources_memory(value=memory, unit="B")

        return self

    def cpu(self, cpu: int) -> Self:
        self.xml_model.vcpu = lvdomain.resources_vcpu(value=cpu)

        return self

    def efi(self, loader: str | Path, nvram: str | Path) -> Self:
        assert self.xml_model.os is not None

        self.xml_model.os.loader = lvdomain.loader(
            value=str(Path(loader).resolve()), type="pflash", readonly="yes"
        )
        self.xml_model.os.nvram = lvdomain.os_nvram(
            value=str(Path(nvram).resolve()), format="qcow2"
        )

        return self

    def kernel(
        self,
        kernel: str | Path,
        initrd: str | Path | None = None,
        cmdline: str | None = None,
    ) -> Self:
        assert self.xml_model.os is not None

        self.xml_model.os.kernel = lvdomain.kernel(value=str(Path(kernel).resolve()))

        if initrd is not None:
            self.xml_model.os.initrd = lvdomain.initrd(
                value=str(Path(initrd).resolve())
            )

        if cmdline is not None:
            self.xml_model.os.cmdline = lvdomain.cmdline(value=cmdline)

        return self

    def disk(self, xml: str) -> Self:
        assert (
            self.xml_model.devices is not None
            and self.xml_model.devices.disk_list is not None
        )
        assert (
            self.xml_model.os is not None
            and (arch := self.xml_model.os.type.arch) is not None
        )

        bus_prefixes: dict[str, str] = {
            "ide": "hd",
            "fdc": "fd",
            "virtio": "vd",
            "xen": "xvd",
            "uml": "ubd",
        }

        d = DiskBuilder.parse(xml)
        bus = d.xml_model.target.bus or ARCH_DEFAULTS[arch].disk_bus

        prefix = bus_prefixes.get(bus, "sd") if bus is not None else "sd"

        suffix = ""
        index = len(self.xml_model.devices.disk_list) + 1
        while index > 0:
            index, remainder = divmod(index - 1, 26)
            suffix = chr(ord("a") + remainder) + suffix

        d.xml_model.target = lvdomain.disk_target(
            dev=prefix + suffix, bus=cast(Any, bus)
        )

        self.xml_model.devices.disk_list.append(d.xml_model)

        return self

    def next_pci_address(self) -> lvdomain.diskspec_address | None:
        assert (
            self.xml_model.devices is not None
            and self.xml_model.devices.interface_list is not None
            and self.xml_model.devices.controller_list is not None
        )
        assert (
            self.xml_model.os is not None
            and (arch := self.xml_model.os.type.arch) is not None
        )

        slots = ARCH_DEFAULTS[arch].pci_slots
        if slots is None:
            return None

        devices: list[lvdomain.devices_interface | lvdomain.controller] = [
            *self.xml_model.devices.interface_list,
            *self.xml_model.devices.controller_list,
        ]
        used = {d.address.slot for d in devices if d.address is not None}
        try:
            slot = next(slot for slot in slots if slot not in used)
        except StopIteration:
            raise RuntimeError(
                f"no free PCI slot left for {arch} (all of {slots} are used)"
            ) from None

        return lvdomain.diskspec_address(
            type="pci", domain=0, bus=0, slot=slot, function=0
        )

    def interface(self, network_xml: str, interface_xml: str | None = None) -> Self:
        assert (
            self.xml_model.devices is not None
            and self.xml_model.devices.interface_list is not None
        )

        assert (
            self.xml_model.os is not None
            and (arch := self.xml_model.os.type.arch) is not None
        )

        if interface_xml is not None:
            i = InterfaceBuilder.parse(interface_xml)
        else:
            i = InterfaceBuilder()
            i.xml_model.model = lvdomain.interface_options_model(
                type=cast(Any, ARCH_DEFAULTS[arch].nic)
            )
        n = NetworkBuilder.parse(network_xml)

        i.xml_model.source = lvdomain.interface_source(network=n.xml_model.name.value)
        # Don't clobber an address the caller already set via `interface_xml`.
        if i.xml_model.address is None:
            i.xml_model.address = self.next_pci_address()

        self.xml_model.devices.interface_list.append(i.xml_model)

        return self

    def default_type(self) -> Self:
        self.xml_model.type = (
            "kvm"
            if self.xml_model.os is not None
            and self.xml_model.os.type.arch is not None
            and have_kvm(self.xml_model.os.type.arch)
            else "qemu"
        )

        return self

    def default_machine(self) -> Self:
        assert (
            self.xml_model.os is not None
            and (arch := self.xml_model.os.type.arch) is not None
        )

        self.xml_model.os.type.machine = ARCH_DEFAULTS[arch].machine

        return self

    def default_cpu(self) -> Self:
        assert self.xml_model.os is not None and self.xml_model.os.type.arch is not None

        if self.xml_model.type == "kvm":
            self.xml_model.cpu = lvdomain.guestcpu(
                mode="host-passthrough", check="none", migratable="on"
            )
        elif (mode := ARCH_DEFAULTS[self.xml_model.os.type.arch].tcg_cpu) is not None:
            self.xml_model.cpu = lvdomain.guestcpu(mode=cast(Any, mode))

        return self

    def default_features(self) -> Self:
        assert (
            self.xml_model.os is not None
            and (arch := self.xml_model.os.type.arch) is not None
        )

        metadata = ARCH_DEFAULTS[arch]
        if metadata.apic or metadata.acpi or metadata.gic:
            self.xml_model.features = lvdomain.features(
                apic=lvdomain.apic() if metadata.apic else None,
                acpi=lvdomain.features_acpi() if metadata.acpi else None,
                gic=lvdomain.gic(version="3") if metadata.gic else None,
            )

        return self

    def default_devices(self) -> Self:
        assert (
            self.xml_model.devices is not None
            and self.xml_model.devices.video_list is not None
            and self.xml_model.devices.graphics_list is not None
            and self.xml_model.devices.input_list is not None
            and self.xml_model.devices.controller_list is not None
            and self.xml_model.devices.console_list is not None
        )
        assert (
            self.xml_model.os is not None
            and (arch := self.xml_model.os.type.arch) is not None
        )

        self.xml_model.devices.video_list.extend(
            [
                lvdomain.video(
                    model=lvdomain.video_model(
                        type=cast(Any, ARCH_DEFAULTS[arch].video)
                    )
                ),
            ]
        )
        self.xml_model.devices.graphics_list.extend(
            [
                lvdomain.graphics(type="vnc", port=-1),
            ]
        )
        self.xml_model.devices.input_list.extend(
            [
                lvdomain.devices_input(type="tablet", bus="usb"),
                lvdomain.devices_input(type="keyboard", bus="usb"),
            ]
        )
        if ARCH_DEFAULTS[arch].pcie:
            self.xml_model.devices.controller_list.extend(
                [
                    lvdomain.controller(type="pci", index=0, model="pcie-root"),
                ]
            )
        self.xml_model.devices.controller_list.extend(
            [
                lvdomain.controller(
                    type="usb",
                    index=0,
                    model=cast(Any, ARCH_DEFAULTS[arch].usb_model),
                    address=self.next_pci_address(),
                ),
            ]
        )
        self.xml_model.devices.console_list.extend(
            [
                lvdomain.console(
                    type="pty",
                    target=lvdomain.qemucdev_tgt_def(
                        type=cast(Any, ARCH_DEFAULTS[arch].console_target)
                    ),
                ),
            ]
        )

        return self

    def qemu_args(self, *args: str) -> Self:
        if self.xml_model.commandline is None:
            self.xml_model.commandline = lvdomain.commandline(arg_list=[])
        assert self.xml_model.commandline.arg_list is not None

        self.xml_model.commandline.arg_list.extend(lvdomain.arg(value=a) for a in args)

        return self

    def default_qemu_args(self) -> Self:
        assert (
            self.xml_model.os is not None
            and (arch := self.xml_model.os.type.arch) is not None
        )

        if ARCH_DEFAULTS[arch].qemu_args:
            self.qemu_args(*ARCH_DEFAULTS[arch].qemu_args)

        return self

    def default(self) -> Self:
        return (
            self.default_type()
            .default_machine()
            .default_cpu()
            .default_features()
            .default_devices()
            .default_qemu_args()
        )


class SnapshotBuilder(Builder[lvdomainsnapshot.domainsnapshot]):
    xml_model_type = lvdomainsnapshot.domainsnapshot

    def __init__(
        self,
        name: str | None = None,
        xml_model: lvdomainsnapshot.domainsnapshot | None = None,
    ) -> None:
        self.xml_model = xml_model or lvdomainsnapshot.domainsnapshot(
            name=lvdomainsnapshot.name(value=name or f"susa-{random_id(10)}")
        )
