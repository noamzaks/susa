from __future__ import annotations

import platform
from dataclasses import dataclass
from pathlib import Path


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
    "i686": ArchDefaults(
        "q35",
        apic=True,
        disk_bus="sata",
        qemu_args=("-cpu", "qemu32,family=4"),
    ),
}


# The host's architecture, by libvirt's name for it.
def host_arch() -> str:
    machine = platform.machine()
    if machine in ("aarch64", "arm64"):
        return "aarch64"
    if machine in ("x86_64", "amd64", "AMD64"):
        return "x86_64"
    raise ValueError(f"Unknown host architecture: {machine!r}")


def have_kvm(arch: str) -> bool:
    return arch == host_arch() and Path("/dev/kvm").exists()
