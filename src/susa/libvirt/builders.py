import ipaddress
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar, Generic, Self, TypeVar, cast

import pydantic_libvirt.domain as lvdomain
import pydantic_libvirt.domainsnapshot as lvsnapshot
import pydantic_libvirt.network as lvnetwork
import pydantic_xml

from susa.utilities import host_arch, random_id


class Builder[T: pydantic_xml.BaseXmlModel](ABC):
    xml_model: T
    xml_model_type: ClassVar[type[pydantic_xml.BaseXmlModel]]

    @abstractmethod
    def __init__(self, xml_model: T | None = None) -> None: ...

    def build(self) -> str:
        tree = self.xml_model.to_xml_tree(skip_empty=True)
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
        self.xml_model.model = lvdomain.interface_options_model(type="virtio")

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

    def disk(self, xml: str) -> Self:
        assert (
            self.xml_model.devices is not None
            and self.xml_model.devices.disk_list is not None
        )

        bus_prefixes: dict[str, str] = {
            "ide": "hd",
            "fdc": "fd",
            "virtio": "vd",
            "xen": "xvd",
            "uml": "ubd",
        }

        d = DiskBuilder.parse(xml)
        bus = d.xml_model.target.bus

        prefix = bus_prefixes.get(bus, "sd") if bus is not None else "sd"

        suffix = ""
        index = len(self.xml_model.devices.disk_list) + 1
        while index > 0:
            index, remainder = divmod(index - 1, 26)
            suffix = chr(ord("a") + remainder) + suffix

        d.xml_model.target = lvdomain.disk_target(dev=prefix + suffix, bus=bus)

        self.xml_model.devices.disk_list.append(d.xml_model)

        return self

    def interface(self, network_xml: str, interface_xml: str | None = None) -> Self:
        assert (
            self.xml_model.devices is not None
            and self.xml_model.devices.interface_list is not None
        )

        i = (
            InterfaceBuilder.parse(interface_xml)
            if interface_xml is not None
            else InterfaceBuilder().default()
        )
        n = NetworkBuilder.parse(network_xml)

        i.xml_model.source = lvdomain.interface_source(network=n.xml_model.name.value)

        self.xml_model.devices.interface_list.append(i.xml_model)

        return self

    def default_type(self) -> Self:
        self.xml_model.type = (
            "kvm"
            if self.xml_model.os is not None
            and self.xml_model.os.type.arch == host_arch()
            else "qemu"
        )

        return self

    def default_machine(self) -> Self:
        assert (
            self.xml_model.os is not None
            and (arch := self.xml_model.os.type.arch) is not None
        )

        match arch:
            case "x86_64":
                machine = "pc"
            case "aarch64":
                machine = "virt"
            case _:
                raise ValueError(f"Unknown default machine for {arch!r}")

        self.xml_model.os.type.machine = machine

        return self

    def default_cpu(self) -> Self:
        self.xml_model.cpu = (
            lvdomain.guestcpu(mode="host-passthrough", check="none", migratable="on")
            if self.xml_model.type == "kvm"
            else lvdomain.guestcpu(
                mode="custom", match="exact", model=lvdomain.cpu_model(value="max")
            )
        )

        return self

    def default_features(self) -> Self:
        self.xml_model.features = lvdomain.features(
            acpi=lvdomain.features_acpi(), apic=lvdomain.apic()
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

        self.xml_model.devices.video_list.extend(
            [
                lvdomain.video(model=lvdomain.video_model(type="virtio")),
            ]
        )
        self.xml_model.devices.graphics_list.extend(
            [
                lvdomain.graphics(type="vnc", port=-1),
            ]
        )
        self.xml_model.devices.input_list.extend(
            [
                lvdomain.devices_input(type="mouse", bus="usb"),
                lvdomain.devices_input(type="keyboard", bus="usb"),
            ]
        )
        self.xml_model.devices.controller_list.extend(
            [
                lvdomain.controller(type="pci", index=0, model="pcie-root"),
                lvdomain.controller(type="usb", index=0),
            ]
        )
        self.xml_model.devices.console_list.extend(
            [
                lvdomain.console(
                    type="pty", target=lvdomain.qemucdev_tgt_def(type="serial")
                ),
            ]
        )

        return self

    def default(self) -> Self:
        return (
            self.default_type()
            .default_machine()
            .default_cpu()
            .default_features()
            .default_devices()
        )
