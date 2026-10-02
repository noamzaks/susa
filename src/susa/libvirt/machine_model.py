from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pydantic_libvirt.domain as lvdomain
import pydantic_libvirt.domainsnapshot as lvdomainsnapshot
from typing_extensions import Self

from susa.libvirt.arch import ARCH_DEFAULTS, ArchDefaults, have_kvm
from susa.libvirt.disk_model import DiskModel
from susa.libvirt.interface_model import InterfaceModel
from susa.libvirt.model import Model
from susa.utilities.generic import random_id

# The device names libvirt gives disks on each bus ("sd" for any other).
BUS_PREFIXES = {"ide": "hd", "fdc": "fd", "virtio": "vd", "xen": "xvd", "uml": "ubd"}


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

    def name(self, name: str) -> Self:
        self.xml_model.name = lvdomain.name(value=name)

        return self

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

    def disk(self, disk: DiskModel) -> Self:
        disks = self.get_devices().disk_list
        assert disks is not None

        bus = disk.xml_model.target.bus or self.get_defaults().disk_bus
        prefix = BUS_PREFIXES.get(bus, "sd") if bus is not None else "sd"
        # Like libvirt names them: a, ..., z, aa, ab, ...
        suffix = ""
        index = len(disks) + 1
        while index > 0:
            index, remainder = divmod(index - 1, 26)
            suffix = chr(ord("a") + remainder) + suffix
        disk.xml_model.target = lvdomain.disk_target(
            dev=prefix + suffix, bus=cast(Any, bus)
        )
        disks.append(disk.xml_model)

        return self

    def next_pci_address(self) -> lvdomain.diskspec_address | None:
        slots = self.get_defaults().pci_slots
        if slots is None:
            return None

        devices = self.get_devices()
        assert (
            devices.interface_list is not None and devices.controller_list is not None
        )
        addressed: list[lvdomain.devices_interface | lvdomain.controller] = [
            *devices.interface_list,
            *devices.controller_list,
        ]
        used = {d.address.slot for d in addressed if d.address is not None}
        free = [slot for slot in slots if slot not in used]
        if not free:
            raise RuntimeError(f"There's no free PCI slot left (of {slots})")

        return lvdomain.diskspec_address(
            type="pci", domain=0, bus=0, slot=free[0], function=0
        )

    def interface(self, interface: InterfaceModel) -> Self:
        interfaces = self.get_devices().interface_list
        assert interfaces is not None

        if interface.xml_model.model is None:
            interface.default_model(self.get_arch())
        if interface.xml_model.address is None:
            interface.xml_model.address = self.next_pci_address()
        interfaces.append(interface.xml_model)

        return self

    def default_type(self) -> Self:
        self.xml_model.type = "kvm" if have_kvm(self.get_arch()) else "qemu"

        return self

    def default_machine(self) -> Self:
        assert self.xml_model.os is not None

        self.xml_model.os.type.machine = self.get_defaults().machine

        return self

    def default_cpu(self) -> Self:
        if self.xml_model.type == "kvm":
            self.xml_model.cpu = lvdomain.guestcpu(
                mode="host-passthrough", check="none", migratable="on"
            )
        elif (mode := self.get_defaults().tcg_cpu) is not None:
            self.xml_model.cpu = lvdomain.guestcpu(mode=cast(Any, mode))

        return self

    def default_features(self) -> Self:
        defaults = self.get_defaults()
        if not (defaults.apic or defaults.acpi or defaults.gic):
            return self

        self.xml_model.features = lvdomain.features(
            apic=lvdomain.apic() if defaults.apic else None,
            acpi=lvdomain.features_acpi() if defaults.acpi else None,
            gic=lvdomain.gic(version="3") if defaults.gic else None,
        )

        return self

    def default_devices(self) -> Self:
        defaults = self.get_defaults()
        devices = self.get_devices()
        assert (
            devices.video_list is not None
            and devices.graphics_list is not None
            and devices.input_list is not None
            and devices.controller_list is not None
            and devices.console_list is not None
        )

        devices.video_list.append(
            lvdomain.video(model=lvdomain.video_model(type=cast(Any, defaults.video)))
        )
        devices.graphics_list.append(lvdomain.graphics(type="vnc", port=-1))
        devices.input_list += [
            lvdomain.devices_input(type="tablet", bus="usb"),
            lvdomain.devices_input(type="keyboard", bus="usb"),
        ]
        if defaults.pcie:
            devices.controller_list.append(
                lvdomain.controller(type="pci", index=0, model="pcie-root")
            )
        devices.controller_list.append(
            lvdomain.controller(
                type="usb",
                index=0,
                model=cast(Any, defaults.usb_model),
                address=self.next_pci_address(),
            )
        )
        devices.console_list.append(
            lvdomain.console(
                type="pty",
                target=lvdomain.qemucdev_tgt_def(
                    type=cast(Any, defaults.console_target)
                ),
            )
        )

        return self

    def qemu_args(self, *args: str) -> Self:
        if self.xml_model.qemu_commandline is None:
            self.xml_model.qemu_commandline = lvdomain.qemucmdline(arg_list=[])
        assert self.xml_model.qemu_commandline.arg_list is not None

        self.xml_model.qemu_commandline.arg_list.extend(
            lvdomain.qemucmdline_arg(value=a) for a in args
        )

        return self

    def default_qemu_args(self) -> Self:
        args = self.get_defaults().qemu_args
        if not args:
            return self

        return self.qemu_args(*args)

    def default(self) -> Self:
        return (
            self.default_type()
            .default_machine()
            .default_cpu()
            .default_features()
            .default_devices()
            .default_qemu_args()
        )

    def get_arch(self) -> str:
        assert (
            self.xml_model.os is not None and self.xml_model.os.type.arch is not None
        ), "Set the architecture with `arch` first!"

        return self.xml_model.os.type.arch

    def get_name(self) -> str:
        return self.xml_model.name.value

    def get_defaults(self) -> ArchDefaults:
        return ARCH_DEFAULTS[self.get_arch()]

    def get_devices(self) -> lvdomain.devices:
        assert self.xml_model.devices is not None

        return self.xml_model.devices

    def get_interfaces(self) -> list[InterfaceModel]:
        return [
            InterfaceModel(xml_model=i) for i in self.get_devices().interface_list or []
        ]

    def get_nvram(self) -> str | None:
        if self.xml_model.os is None or self.xml_model.os.nvram is None:
            return None

        return self.xml_model.os.nvram.value


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

    def name(self, name: str) -> Self:
        self.xml_model.name = lvdomainsnapshot.name(value=name)

        return self

    def get_name(self) -> str:
        assert self.xml_model.name is not None

        return self.xml_model.name.value
