from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Emulation:
    arch: str
    machine: str
    emulator: str
    acpi: bool = False
    smbios: bool = False
    qemu_args: tuple[str, ...] = ()
    expressions: tuple[str, ...] = ()

    @property
    def script(self) -> str:
        expressions = [
            f's#<type [^>]*>hvm</type>#<type arch="{self.arch}" machine="{self.machine}">hvm</type>#',
            "s#<loader[^>]*>[^<]*</loader>##",
            "s#<nvram[^>]*>[^<]*</nvram>##",
            "s#<gic[^>]*></gic>##",
            "s#<cpu[^>]*>.*</cpu>##",
            "s#<emulator>[^<]*</emulator>##",
            f"s#<devices>#<devices><emulator>/usr/bin/{self.emulator}</emulator>#",
            's#<controller type="pci"[^>]*></controller>##g',
            *self.expressions,
        ]
        if not self.acpi:
            expressions.append("s#<acpi></acpi>##")
        if not self.smbios:
            expressions.append("s#<smbios[^>]*></smbios>##")
        if self.qemu_args:
            args = "".join(f'<qemu:arg value="{a}"></qemu:arg>' for a in self.qemu_args)
            expressions.append(
                f"s#</domain>#<qemu:commandline>{args}</qemu:commandline></domain>#"
            )
        return _sed(expressions)


def aarch64_without_kvm_script() -> str:
    return _sed(
        [
            r's#<cpu mode="host-passthrough"[^>]*>#<cpu mode="custom" match="exact"><model fallback="allow">max</model>#',
            's#<features>#<features><gic version="3"></gic>#',
        ]
    )


def cross_architecture_script() -> str:
    return _sed(['s#<cpu[^>]*>.*</cpu>#<cpu mode="maximum"></cpu>#'])


def _sed(expressions: list[str]) -> str:
    arguments = " ".join(f"-e '{e}'" for e in expressions)
    return f'#!/bin/sh\necho "$4" | sed -z -E {arguments}\n'


EMULATIONS = {
    "i686": Emulation(
        "i686",
        "q35",
        "qemu-system-i386",
        acpi=True,
        smbios=True,
        qemu_args=("-cpu", "qemu32,family=4"),
    ),
    "ppc64le": Emulation("ppc64le", "pseries", "qemu-system-ppc64"),
    "riscv64": Emulation("riscv64", "virt", "qemu-system-riscv64"),
    "armv7l": Emulation(
        "armv7l",
        "virt",
        "qemu-system-arm",
        qemu_args=("-machine", "virt,highmem=off"),
    ),
    "mips": Emulation(
        "mips",
        "malta",
        "qemu-system-mips",
        expressions=(
            's#<controller type="(scsi|virtio-serial)"[^>]*>(</controller>)?##g',
            "s#<channel.*</channel>##",
            "s#<input [^>]*></input>##g",
            "s#<rng.*</rng>##",
            's#<memballoon[^>]*>(</memballoon>)?#<memballoon model="none">#',
            's# model="virtio-non-transitional"##g',
            's#<target bus="virtio" dev="vda"></target>#<target bus="ide" dev="sda"></target>#',
            's#<model type="virtio[^"]*"[^>]*></model>#<model type="cirrus"></model>#',
        ),
    ),
}
