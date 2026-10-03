from __future__ import annotations

import platform
from dataclasses import dataclass
from pathlib import Path


# What works on each architecture (by libvirt's name for it), as `MachineModel` builder arguments.
@dataclass(frozen=True)
class ArchDefaults:
    machine: str
    acpi: bool = True
    gic: bool = False
    # The CPU when emulating (KVM passes the host's through).
    tcg_cpu: str | None = None
    video: str = "virtio"
    # Extra QEMU arguments libvirt has no XML for.
    qemu_args: tuple[str, ...] = ()

    # How `MachineModel.disk()` and `interface()` attach devices (unless they're told otherwise).
    disk_bus: str | None = None
    nic: str = "e1000"
    # If set, the only PCI slots that get an interrupt (libvirt would pick others).
    pci_slots: tuple[int, ...] | None = None


ARCH_DEFAULTS: dict[str, ArchDefaults] = {
    "x86_64": ArchDefaults("q35", disk_bus="sata"),
    "aarch64": ArchDefaults(
        "virt", gic=True, tcg_cpu="maximum", disk_bus="virtio", nic="virtio"
    ),
    "mips": ArchDefaults(
        "malta",
        acpi=False,
        # Malta's kernels only have a framebuffer driver for Cirrus.
        video="cirrus",
        disk_bus="ide",
        # Malta only routes interrupts to PCI slots 11 and 12.
        pci_slots=(11, 12),
    ),
    "ppc64le": ArchDefaults("pseries", acpi=False, video="vga", disk_bus="virtio"),
    "armv7l": ArchDefaults(
        "virt",
        acpi=False,
        # A 32-bit guest can't reach the PCI window above 4 GB.
        qemu_args=("-machine", "virt,highmem=off"),
        disk_bus="virtio",
    ),
    "riscv64": ArchDefaults("virt", disk_bus="virtio", nic="virtio"),
    "i686": ArchDefaults(
        "q35",
        # An i486-class CPU, since a true i386 crashes any kernel newer than ~2013.
        qemu_args=("-cpu", "qemu32,family=4"),
        disk_bus="sata",
    ),
}


# The host's architecture, by libvirt's name for it.
def host_arch() -> str:
    machine = platform.machine()
    return {"arm64": "aarch64", "amd64": "x86_64", "AMD64": "x86_64"}.get(
        machine, machine
    )


def have_kvm(arch: str) -> bool:
    return arch == host_arch() and Path("/dev/kvm").exists()
