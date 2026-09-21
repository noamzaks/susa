import logging
import subprocess
import sys
import tempfile
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path

import IPython

from susa.libvirt.builders import DiskBuilder, DomainBuilder, NetworkBuilder
from susa.libvirt.connection import Connection
from susa.libvirt.machine import Machine
from susa.libvirt.network import Network
from susa.linked_clone import LinkedClone
from susa.utilities import GIGA

MACHINES = Path("/machines")
logger = logging.getLogger(__name__)


@contextmanager
def tmp_dir_path() -> Generator[Path]:
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir)
        p.chmod(0o777)
        yield p


def nvram(tmp: Path, vars: str) -> Path:
    path = tmp / "vars.qcow2"
    subprocess.run(
        ["qemu-img", "convert", "-f", "raw", "-O", "qcow2", vars, path], check=True
    )
    return path


def finish(builder: DomainBuilder, disk: Path, network_xml: str) -> str:
    disk_xml = DiskBuilder().source(disk).build()
    xml = builder.interface(network_xml).disk(disk_xml).build()
    logger.info(xml)
    return xml


# Each of the following builds the XML of a machine booting the Debian image `disk`
# (see `DISKS`), with `tmp` as a place for its per-run files.


def x86_64(disk: Path, tmp: Path, network_xml: str) -> str:
    vars = nvram(tmp, "/usr/share/OVMF/OVMF_VARS.fd")
    return finish(
        DomainBuilder()
        .arch("x86_64")
        .default()
        .memory(2 * GIGA)
        .cpu(2)
        .efi("/usr/share/OVMF/OVMF_CODE.fd", vars),
        disk,
        network_xml,
    )


def aarch64(disk: Path, tmp: Path, network_xml: str) -> str:
    vars = nvram(tmp, "/usr/share/AAVMF/AAVMF_VARS.fd")
    return finish(
        DomainBuilder()
        .arch("aarch64")
        .default()
        .memory(2 * GIGA)
        .cpu(2)
        .efi("/usr/share/AAVMF/AAVMF_CODE.fd", vars),
        disk,
        network_xml,
    )


def mips(disk: Path, tmp: Path, network_xml: str) -> str:
    # Malta has no firmware, so the kernel and initrd come from outside the disk.
    boot = MACHINES / "debian-mips-boot"
    return finish(
        DomainBuilder()
        .arch("mips")
        .default()
        .memory(2 * GIGA)
        .cpu(1)
        .kernel(
            boot / "vmlinux-4.19.0-21-4kc-malta",
            boot / "initrd.img-4.19.0-21-4kc-malta",
            "root=/dev/sda1 console=tty0 console=ttyS0",
        ),
        disk,
        network_xml,
    )


def ppc64le(disk: Path, tmp: Path, network_xml: str) -> str:
    # The disk has its own bootloader (grub-ieee1275 in a PReP partition).
    return finish(
        DomainBuilder().arch("ppc64le").default().memory(2 * GIGA).cpu(2),
        disk,
        network_xml,
    )


def armv7l(disk: Path, tmp: Path, network_xml: str) -> str:
    # There's no firmware or bootloader, so the kernel and initrd come from outside
    # the disk.
    boot = MACHINES / "debian-armhf-boot"
    return finish(
        DomainBuilder()
        .arch("armv7l")
        .default()
        .memory(2 * GIGA)
        .cpu(1)
        .kernel(
            boot / "vmlinuz-6.12.107+deb13-armmp",
            boot / "initrd.img-6.12.107+deb13-armmp",
            "root=/dev/vda1 rw console=tty0 console=ttyAMA0 net.ifnames=0",
        ),
        disk,
        network_xml,
    )


def riscv64(disk: Path, tmp: Path, network_xml: str) -> str:
    # The installer can't set up a bootloader when booted without firmware (as it is
    # here), so the kernel and initrd come from outside the disk.
    boot = MACHINES / "debian-riscv64-boot"
    return finish(
        DomainBuilder()
        .arch("riscv64")
        .default()
        .memory(2 * GIGA)
        .cpu(2)
        .kernel(
            boot / "vmlinuz-6.12.107+deb13-riscv64",
            boot / "initrd.img-6.12.107+deb13-riscv64",
            "root=/dev/vda3 rw console=tty0 console=ttyS0",
        ),
        disk,
        network_xml,
    )


ARCHITECTURES: dict[str, Callable[[Path, Path, str], str]] = {
    "x86_64": x86_64,
    "aarch64": aarch64,
    "mips": mips,
    "ppc64le": ppc64le,
    "armv7l": armv7l,
    "riscv64": riscv64,
}

# All of these have sshd on, and `root` and `user` with the password `a`.
DISKS = {arch: MACHINES / f"debian_{arch}.qcow2" for arch in ARCHITECTURES} | {
    "x86_64": MACHINES / "debian_x86_64_new.qcow2"
}


def main() -> None:
    logging.basicConfig(level=logging.INFO)

    arch = sys.argv[1] if len(sys.argv) > 1 else "mips"

    with tmp_dir_path() as d:
        # Work on a clone, so the original image stays pristine.
        clone = LinkedClone(d / "disk.qcow2", DISKS[arch])
        network_xml = NetworkBuilder().default().ip("10.0.0.1").nat().build()
        machine_xml = ARCHITECTURES[arch](Path(clone.path), d, network_xml)
        print(machine_xml)

        with (
            Connection("qemu:///system"),
            Network(network_xml),
            Machine(machine_xml) as m,
        ):
            print(m)
            IPython.embed(colors="linux")
