import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Self, cast

import pydantic_libvirt.domain as lvdomain
import pydantic_libvirt.domainsnapshot as lvdomainsnapshot
from typing_extensions import override

from susa.libvirt.arch import ARCH_DEFAULTS, have_kvm
from susa.libvirt.disk_model import DiskModel
from susa.libvirt.interface_model import InterfaceModel
from susa.libvirt.model import Model
from susa.utilities.generic import random_id

QEMU_NAMESPACE = "http://libvirt.org/schemas/domain/qemu/1.0"

ET.register_namespace("qemu", QEMU_NAMESPACE)


class MachineModel(Model[lvdomain.domain]):
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

    @override
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

    def get_arch(self) -> str:
        assert (
            self.xml_model.os is not None and self.xml_model.os.type.arch is not None
        ), "Set the architecture with `arch` first!"

        return self.xml_model.os.type.arch

    def get_name(self) -> str:
        return self.xml_model.name.value

    def get_interfaces(self) -> list[InterfaceModel]:
        assert self.xml_model.devices is not None

        return [
            InterfaceModel(xml_model=i)
            for i in self.xml_model.devices.interface_list or []
        ]

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

    def get_nvram(self) -> str | None:
        """The path of the machine's UEFI variables, if it has any."""
        if self.xml_model.os is None or self.xml_model.os.nvram is None:
            return None

        return self.xml_model.os.nvram.value

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

    def disk(self, disk: DiskModel) -> Self:
        assert (
            self.xml_model.devices is not None
            and self.xml_model.devices.disk_list is not None
        )
        arch = self.get_arch()

        bus_prefixes: dict[str, str] = {
            "ide": "hd",
            "fdc": "fd",
            "virtio": "vd",
            "xen": "xvd",
            "uml": "ubd",
        }

        bus = disk.xml_model.target.bus or ARCH_DEFAULTS[arch].disk_bus

        prefix = bus_prefixes.get(bus, "sd") if bus is not None else "sd"

        suffix = ""
        index = len(self.xml_model.devices.disk_list) + 1
        while index > 0:
            index, remainder = divmod(index - 1, 26)
            suffix = chr(ord("a") + remainder) + suffix

        disk.xml_model.target = lvdomain.disk_target(
            dev=prefix + suffix, bus=cast(Any, bus)
        )

        self.xml_model.devices.disk_list.append(disk.xml_model)

        return self

    def next_pci_address(self) -> lvdomain.diskspec_address | None:
        assert (
            self.xml_model.devices is not None
            and self.xml_model.devices.interface_list is not None
            and self.xml_model.devices.controller_list is not None
        )
        arch = self.get_arch()

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

    def interface(self, interface: InterfaceModel) -> Self:
        assert (
            self.xml_model.devices is not None
            and self.xml_model.devices.interface_list is not None
        )

        if interface.xml_model.address is None:
            interface.xml_model.address = self.next_pci_address()

        self.xml_model.devices.interface_list.append(interface.xml_model)

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
        arch = self.get_arch()
        assert self.xml_model.os is not None

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
        arch = self.get_arch()

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
        arch = self.get_arch()

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
        arch = self.get_arch()

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


class SnapshotModel(Model[lvdomainsnapshot.domainsnapshot]):
    xml_model_type = lvdomainsnapshot.domainsnapshot

    def __init__(
        self,
        name: str | None = None,
        xml_model: lvdomainsnapshot.domainsnapshot | None = None,
    ) -> None:
        self.xml_model = xml_model or lvdomainsnapshot.domainsnapshot(
            name=lvdomainsnapshot.name(value=name or f"susa-{random_id(10)}")
        )

    def get_name(self) -> str:
        assert self.xml_model.name is not None

        return self.xml_model.name.value
