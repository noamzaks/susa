from __future__ import annotations

import random
import subprocess
from collections.abc import Callable, Generator
from pathlib import Path

import pytest

from susa import tmp_dir_path
from susa.communicator.serial import SerialCommunicator
from susa.communicator.shell import ShellCommunicator, login
from susa.communicator.ssh import SSHCommunicator
from susa.libvirt.connection import Connection
from susa.libvirt.disk_model import DiskModel
from susa.libvirt.interface_model import InterfaceModel
from susa.libvirt.machine import LVMachine, LVSnapshot
from susa.libvirt.machine_model import MachineModel
from susa.libvirt.network import LVNetwork
from susa.libvirt.network_model import NetworkModel
from susa.linked_clone import LinkedClone
from susa.utilities.generic import GIGA
from susa.utilities.networking import ping, wait_until_ping

MACHINES = Path("/machines")
BOOT_TIMEOUT = 120


def nvram(tmp: Path, vars: str) -> Path:
    path = tmp / "vars.qcow2"
    subprocess.run(
        ["qemu-img", "convert", "-f", "raw", "-O", "qcow2", vars, path], check=True
    )
    return path


def finish(domain: MachineModel, disk: Path, network: NetworkModel) -> MachineModel:
    interface = InterfaceModel().default(domain.get_arch())
    network.interface(interface)
    return domain.interface(interface).disk(DiskModel().source(disk))


# Each of the following builds the model of a machine booting the Debian image `disk`
# (see `DISKS`), with `tmp` as a place for its per-run files.


def x86_64(disk: Path, tmp: Path, network: NetworkModel) -> MachineModel:
    vars = nvram(tmp, "/usr/share/OVMF/OVMF_VARS.fd")
    return finish(
        MachineModel()
        .arch("x86_64")
        .default()
        .memory(2 * GIGA)
        .cpu(2)
        .efi("/usr/share/OVMF/OVMF_CODE.fd", vars),
        disk,
        network,
    )


def aarch64(disk: Path, tmp: Path, network: NetworkModel) -> MachineModel:
    vars = nvram(tmp, "/usr/share/AAVMF/AAVMF_VARS.fd")
    return finish(
        MachineModel()
        .arch("aarch64")
        .default()
        .memory(2 * GIGA)
        .cpu(2)
        .efi("/usr/share/AAVMF/AAVMF_CODE.fd", vars),
        disk,
        network,
    )


def mips(disk: Path, tmp: Path, network: NetworkModel) -> MachineModel:
    # Malta has no firmware, so the kernel and initrd come from outside the disk.
    boot = MACHINES / "debian-mips-boot"
    return finish(
        MachineModel()
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
        network,
    )


def ppc64le(disk: Path, tmp: Path, network: NetworkModel) -> MachineModel:
    # The disk has its own bootloader (grub-ieee1275 in a PReP partition).
    return finish(
        MachineModel().arch("ppc64le").default().memory(2 * GIGA).cpu(2),
        disk,
        network,
    )


def i386(disk: Path, tmp: Path, network: NetworkModel) -> MachineModel:
    # BIOS (SeaBIOS) + grub-pc, installed on the disk itself, so no firmware or
    # kernel/initrd is needed here. "i686" is libvirt's name for this architecture;
    # the CPU is restricted to i486-class since true i386 crashes any kernel newer
    # than ~2013 (see the ArchDefaults comment).
    return finish(
        MachineModel().arch("i686").default().memory(2 * GIGA).cpu(2),
        disk,
        network,
    )


def armv7l(disk: Path, tmp: Path, network: NetworkModel) -> MachineModel:
    # There's no firmware or bootloader, so the kernel and initrd come from outside
    # the disk.
    boot = MACHINES / "debian-armhf-boot"
    return finish(
        MachineModel()
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
        network,
    )


def riscv64(disk: Path, tmp: Path, network: NetworkModel) -> MachineModel:
    # The installer can't set up a bootloader when booted without firmware (as it is
    # here), so the kernel and initrd come from outside the disk.
    boot = MACHINES / "debian-riscv64-boot"
    return finish(
        MachineModel()
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
        network,
    )


def freebsd(disk: Path, tmp: Path, network: NetworkModel) -> MachineModel:
    # BIOS, with the loader, kernel and a getty on the serial console as well.
    return finish(
        MachineModel().arch("x86_64").default().memory(2 * GIGA).cpu(2), disk, network
    )


ARCHITECTURES: dict[str, Callable[[Path, Path, NetworkModel], MachineModel]] = {
    "x86_64": x86_64,
    "aarch64": aarch64,
    "mips": mips,
    "ppc64le": ppc64le,
    "armv7l": armv7l,
    "riscv64": riscv64,
    "i386": i386,
    "freebsd": freebsd,
    "freebsd10": freebsd,
}

# All of these have sshd on, and `root` and `user` with the password `a`. The FreeBSD ones (15.1 and 10.4) use
# its `/bin/sh` rather than bash.
DISKS = {
    name: MACHINES / f"debian_{name}.qcow2"
    for name in ARCHITECTURES
    if not name.startswith("freebsd")
} | {
    "freebsd": MACHINES / "freebsd_x86_64.qcow2",
    "freebsd10": MACHINES / "freebsd10_x86_64.qcow2",
}


@pytest.fixture(scope="session")
def connection() -> Generator[None, None, None]:
    with Connection("qemu:///system"):
        yield


# Each architecture's tests share one worker (see `--dist loadgroup` in pyproject.toml), so it boots once.
@pytest.fixture(
    scope="module",
    params=[pytest.param(a, marks=pytest.mark.xdist_group(a)) for a in ARCHITECTURES],
)
def base_machine(
    request: pytest.FixtureRequest, connection: None
) -> Generator[LVMachine, None, None]:
    """A booted machine of each architecture: answering ping, with a login prompt on its serial console."""
    arch: str = request.param
    if not DISKS[arch].exists():
        pytest.skip(f"{DISKS[arch]} doesn't exist")

    with tmp_dir_path() as tmp:
        clone = LinkedClone(tmp / "disk.qcow2", DISKS[arch])
        # Each architecture gets its own subnet, so machines never share one.
        network = (
            NetworkModel().default().ip(f"10.0.{list(ARCHITECTURES).index(arch)}.1")
        )
        domain = ARCHITECTURES[arch](Path(clone.path), tmp, network)

        with LVNetwork(network) as n, LVMachine(domain, [n]) as machine:
            wait_until_ping(machine.ip, timeout=BOOT_TIMEOUT)
            # Machines may answer ping before they're done booting.
            with machine.serial() as serial:
                serial.write(b"\r")
                serial.read_until(b"login:", timeout=BOOT_TIMEOUT)
            yield machine


@pytest.fixture(scope="module")
def ready(base_machine: LVMachine) -> LVSnapshot:
    return base_machine.snapshot()


@pytest.fixture
def machine(
    base_machine: LVMachine, ready: LVSnapshot
) -> Generator[LVMachine, None, None]:
    """`base_machine`, reverted to when it was ready after the test."""
    yield base_machine
    ready.revert()


def test_ping(machine: LVMachine) -> None:
    assert ping(machine.ip, timeout=5) is not None


def test_screenshot(machine: LVMachine) -> None:
    screenshot = machine.screenshot()
    # PNG or PPM, depending on the QEMU version.
    assert screenshot.data.startswith((b"\x89PNG\r\n\x1a\n", b"P6"))


def test_serial(machine: LVMachine) -> None:
    with machine.serial() as serial:
        # getty prints the prompt again for an empty login.
        serial.write(b"\r")
        serial.read_until(b"login:", timeout=30)

        # Reads stop at `size`, leaving the rest of the (longer) prompt for the next read.
        serial.write(b"\r")
        assert len(serial.read(4, timeout=30)) == 4
        serial.read_until(b"login:", timeout=30)


def communicator(machine: LVMachine, kind: str) -> ShellCommunicator:
    if kind == "serial":
        return SerialCommunicator(machine.serial(), login("root", "a"))
    return SSHCommunicator(machine.ip, "root", "a")


COMMUNICATORS = ("serial", "ssh")
UNAME = {name: name for name in ARCHITECTURES} | {
    # The CPU is i486-class (see `ARCH_DEFAULTS`).
    "i386": "i486",
    "freebsd": "amd64",
    "freebsd10": "amd64",
}


@pytest.fixture
def name(request: pytest.FixtureRequest) -> str:
    """The name (in `ARCHITECTURES`) of the machine the test got."""
    result: str = request.node.callspec.params["base_machine"]
    return result


@pytest.mark.parametrize("kind", COMMUNICATORS)
def test_uname(machine: LVMachine, name: str, kind: str) -> None:
    with communicator(machine, kind) as c:
        result = c.run("uname -m")
        assert (result.returncode, result.stdout, result.stderr) == (
            0,
            f"{UNAME[name]}\n".encode(),
            b"",
        )


@pytest.mark.parametrize("kind", COMMUNICATORS)
def test_run(machine: LVMachine, kind: str) -> None:
    with communicator(machine, kind) as c:
        result = c.run("echo a; echo b >&2; false")
        assert (result.returncode, result.stdout, result.stderr) == (1, b"a\n", b"b\n")
        assert c.execute("cd /tmp; pwd").stdout == b"/tmp\n"
        assert c.execute("pwd").stdout == b"/tmp\n"


@pytest.mark.parametrize("kind", COMMUNICATORS)
def test_start(machine: LVMachine, kind: str) -> None:
    with communicator(machine, kind) as c:
        command = c.start("echo started; sleep 2; echo done >&2")
        assert command.stdout.read_until(b"started\n", timeout=10) == b"started\n"
        assert command.poll() is None
        assert command.wait() == 0
        assert command.stderr.read() == b"done\n"


@pytest.mark.parametrize("kind", COMMUNICATORS)
def test_transfer(machine: LVMachine, kind: str, tmp_path: Path) -> None:
    data = random.randbytes(5000)
    (tmp_path / "up").write_bytes(data)
    with communicator(machine, kind) as c:
        c.upload(tmp_path / "up", "/tmp/susa")
        c.download("/tmp/susa", tmp_path / "down")
    assert (tmp_path / "down").read_bytes() == data


def test_power_cycle(machine: LVMachine) -> None:
    machine.power_off()
    assert not machine.is_powered_on

    machine.power_on()
    assert machine.is_powered_on
    with machine.serial() as serial:
        # Booting may take longer than usual while other machines run in parallel.
        serial.read_until(b"login:", timeout=2 * BOOT_TIMEOUT)
