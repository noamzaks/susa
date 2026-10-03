from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any, TypeVar, cast

import pydantic_libvirt.domain as lvdomain
import pydantic_libvirt.domainsnapshot as lvdomainsnapshot
from typing_extensions import Self

from susa.libvirt.arch import ARCH_DEFAULTS, ArchDefaults, have_kvm
from susa.libvirt.disk_model import DiskModel
from susa.libvirt.interface_model import InterfaceModel
from susa.libvirt.model import Model
from susa.libvirt.network_model import NetworkModel
from susa.libvirt.volume_model import VolumeModel
from susa.utilities.generic import random_id

D = TypeVar("D")

# The device names libvirt gives disks on each bus ("sd" for any other).
BUS_PREFIXES = {"ide": "hd", "fdc": "fd", "virtio": "vd"}


class MachineModel(Model[lvdomain.domain]):
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
            type=lvdomain.os_type(value="hvm", arch=cast(Any, arch))
        )

        return self

    def machine(self, machine: str) -> Self:
        assert self.xml_model.os is not None

        self.xml_model.os.type.machine = machine

        return self

    def memory(self, memory: int) -> Self:
        self.xml_model.memory = lvdomain.resources_memory(value=memory, unit="B")

        return self

    def cpu(self, cpu: int) -> Self:
        self.xml_model.vcpu = lvdomain.resources_vcpu(value=cpu)

        return self

    def features(self, acpi: bool = False, gic: bool = False) -> Self:
        self.xml_model.features = lvdomain.features(
            acpi=lvdomain.features_acpi() if acpi else None,
            gic=lvdomain.gic(version="3") if gic else None,
        )

        return self

    # UEFI firmware, which libvirt picks (by QEMU's firmware descriptors), giving the machine its own copy of its
    # variables.
    def efi(self, secure_boot: bool = False) -> Self:
        assert self.xml_model.os is not None

        self.xml_model.os.firmware = "efi"
        self.xml_model.os.firmware2 = lvdomain.firmware(
            feature_list=[
                lvdomain.feature(
                    enabled="yes" if secure_boot else "no", name="secure-boot"
                )
            ]
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

    def qemu_args(self, args: Sequence[str]) -> Self:
        if self.xml_model.qemu_commandline is None:
            self.xml_model.qemu_commandline = lvdomain.qemucmdline(arg_list=[])
        assert self.xml_model.qemu_commandline.arg_list is not None

        self.xml_model.qemu_commandline.arg_list.extend(
            lvdomain.qemucmdline_arg(value=a) for a in args
        )

        return self

    def video(self, model: str) -> Self:
        video = lvdomain.video(model=lvdomain.video_model(type=cast(Any, model)))
        return self._add(self.get_devices().video_list, video)

    def vnc(self) -> Self:
        vnc = lvdomain.graphics(type="vnc", port=-1)
        return self._add(self.get_devices().graphics_list, vnc)

    def tablet(self) -> Self:
        tablet = lvdomain.devices_input(type="tablet", bus="usb")
        return self._add(self.get_devices().input_list, tablet)

    def keyboard(self) -> Self:
        keyboard = lvdomain.devices_input(type="keyboard", bus="usb")
        return self._add(self.get_devices().input_list, keyboard)

    def usb(self) -> Self:
        usb = lvdomain.controller(type="usb", index=0, address=self.next_pci_address())
        return self._add(self.get_devices().controller_list, usb)

    def console(self) -> Self:
        console = lvdomain.console(type="pty")
        return self._add(self.get_devices().console_list, console)

    def disk(self, disk: DiskModel) -> Self:
        bus = disk.xml_model.target.bus or self.get_defaults().disk_bus
        target = lvdomain.disk_target(dev=self.next_disk_name(bus), bus=cast(Any, bus))
        disk_xml = disk.xml_model.model_copy(update={"target": target})
        return self._add(self.get_devices().disk_list, disk_xml)

    def interface(self, interface: InterfaceModel) -> Self:
        if interface.xml_model.model is None:
            interface.model(self.get_defaults().nic)
        if interface.xml_model.address is None:
            interface.xml_model.address = self.next_pci_address()
        return self._add(self.get_devices().interface_list, interface.xml_model)

    # A disk on a volume (in a storage pool), e.g. an overlay of a base image.
    def volume(self, volume: VolumeModel) -> Self:
        return self.disk(DiskModel().volume(volume))

    def network(self, network: NetworkModel, ip: str | None = None) -> Self:
        interface = InterfaceModel()
        network.interface(interface, ip)
        return self.interface(interface)

    def default_type(self) -> Self:
        self.xml_model.type = "kvm" if have_kvm(self.get_arch()) else "qemu"

        return self

    def default_cpu(self) -> Self:
        if self.xml_model.type == "kvm":
            self.xml_model.cpu = lvdomain.guestcpu(mode="host-passthrough")
        elif (mode := self.get_defaults().tcg_cpu) is not None:
            self.xml_model.cpu = lvdomain.guestcpu(mode=cast(Any, mode))

        return self

    def default(self) -> Self:
        defaults = self.get_defaults()

        self.default_type().machine(defaults.machine).default_cpu()
        self.features(acpi=defaults.acpi, gic=defaults.gic)
        self.video(defaults.video).vnc().tablet().keyboard().usb().console()
        if defaults.qemu_args:
            self.qemu_args(defaults.qemu_args)

        return self

    def _add(self, devices: list[D] | None, device: D) -> Self:
        assert devices is not None

        devices.append(device)

        return self

    # Like libvirt names them: e.g. sda, ..., sdz, sdaa, ...
    def next_disk_name(self, bus: str | None) -> str:
        disks = self.get_devices().disk_list
        assert disks is not None

        prefix = BUS_PREFIXES.get(bus, "sd") if bus is not None else "sd"
        suffix = ""
        index = len(disks) + 1
        while index > 0:
            index, remainder = divmod(index - 1, 26)
            suffix = chr(ord("a") + remainder) + suffix
        return prefix + suffix

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

    def get_name(self) -> str:
        return self.xml_model.name.value

    def get_arch(self) -> str:
        assert (
            self.xml_model.os is not None and self.xml_model.os.type.arch is not None
        ), "Set the architecture with `arch` first!"

        return self.xml_model.os.type.arch

    def get_defaults(self) -> ArchDefaults:
        return ARCH_DEFAULTS[self.get_arch()]

    def get_firmware(self) -> str | None:
        assert self.xml_model.os is not None

        return self.xml_model.os.firmware

    def get_devices(self) -> lvdomain.devices:
        assert self.xml_model.devices is not None

        return self.xml_model.devices

    def get_interfaces(self) -> list[lvdomain.devices_interface] | None:
        return self.get_devices().interface_list


class SnapshotModel(Model[lvdomainsnapshot.domainsnapshot]):
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
