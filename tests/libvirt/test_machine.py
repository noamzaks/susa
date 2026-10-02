from __future__ import annotations

import random
import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from scapy.layers.inet import ICMP, IP

from susa.communicator.shell import ShellCommunicator
from susa.core.machine import wait_until_booted
from susa.libvirt import (
    Connection,
    LVMachine,
    LVNetwork,
    LVSnapshot,
    LVVolume,
    VolumeModel,
)
from susa.recipes import make
from susa.session import Session
from susa.utilities.generic import GIGA, wait_until
from susa.utilities.networking import ping, wait_until_ping

MACHINES = Path("/machines")
BOOT_TIMEOUT = 120
QUIET_TIME = 5


# A base image, and the steps of the machine's recipe for it (setting it up for its architecture, with 2 GB).
@dataclass(frozen=True)
class Image:
    path: Path
    steps: list[Any]

    # A machine on a network with an available IP and a volume of its own backed by the image.
    def session(self, path: Path | None = None) -> list[dict[str, Any]]:
        machine = [
            *self.steps,
            "default",
            {"memory": 2 * GIGA},
            {"volume": {"$ref": "volume.model"}},
            {"network": {"$ref": "network.model"}},
        ]
        return [
            {
                "network": {
                    "susa.libvirt.network.LVNetwork": {"model": ["default", "ip"]}
                }
            },
            {
                "volume": {
                    "susa.libvirt.volume.LVVolume": {
                        "model": [{"backing": str(path or self.path)}]
                    }
                }
            },
            {"machine": {"susa.libvirt.machine.LVMachine": {"model": machine}}},
        ]


IMAGES = {
    "x86_64": Image(
        MACHINES / "debian_x86_64.qcow2", [{"arch": "x86_64"}, {"cpu": 2}, "efi"]
    ),
    "aarch64": Image(
        MACHINES / "debian_aarch64.qcow2", [{"arch": "aarch64"}, {"cpu": 2}, "efi"]
    ),
    # Malta has no firmware, so the kernel and initrd come from outside the disk (and it can't do more CPUs well).
    "mips": Image(
        MACHINES / "debian_mips.qcow2",
        [
            {"arch": "mips"},
            {"cpu": 1},
            {
                "kernel": {
                    "kernel": "/machines/debian-mips-boot/vmlinux-4.19.0-21-4kc-malta",
                    "initrd": "/machines/debian-mips-boot/initrd.img-4.19.0-21-4kc-malta",
                    "cmdline": "root=/dev/sda1 console=tty0 console=ttyS0",
                }
            },
        ],
    ),
    # The disk has its own bootloader (grub-ieee1275 in a PReP partition).
    "ppc64le": Image(
        MACHINES / "debian_ppc64le.qcow2", [{"arch": "ppc64le"}, {"cpu": 2}]
    ),
    # There's no firmware or bootloader, so the kernel and initrd come from outside the disk.
    "armv7l": Image(
        MACHINES / "debian_armv7l.qcow2",
        [
            {"arch": "armv7l"},
            {"cpu": 1},
            {
                "kernel": {
                    "kernel": "/machines/debian-armhf-boot/vmlinuz-6.12.107+deb13-armmp",
                    "initrd": "/machines/debian-armhf-boot/initrd.img-6.12.107+deb13-armmp",
                    "cmdline": "root=/dev/vda1 rw console=tty0 console=ttyAMA0 net.ifnames=0",
                }
            },
        ],
    ),
    # The installer can't set up a bootloader without firmware, so the kernel and initrd come from outside the disk.
    "riscv64": Image(
        MACHINES / "debian_riscv64.qcow2",
        [
            {"arch": "riscv64"},
            {"cpu": 2},
            {
                "kernel": {
                    "kernel": "/machines/debian-riscv64-boot/vmlinuz-6.12.107+deb13-riscv64",
                    "initrd": "/machines/debian-riscv64-boot/initrd.img-6.12.107+deb13-riscv64",
                    "cmdline": "root=/dev/vda3 rw console=tty0 console=ttyS0",
                }
            },
        ],
    ),
    # BIOS (SeaBIOS) and grub-pc on the disk itself. "i686" is libvirt's name for it.
    "i386": Image(MACHINES / "debian_i386.qcow2", [{"arch": "i686"}, {"cpu": 2}]),
    # BIOS, with the loader, kernel and a getty on the serial console as well. FreeBSD 15.1 and 10.4 use its `/bin/sh`
    # rather than bash.
    "freebsd": Image(
        MACHINES / "freebsd_x86_64.qcow2", [{"arch": "x86_64"}, {"cpu": 2}]
    ),
    "freebsd10": Image(
        MACHINES / "freebsd10_x86_64.qcow2", [{"arch": "x86_64"}, {"cpu": 2}]
    ),
}

# All of the images have sshd, telnet and rlogin servers, and `root` and `user` with the password `a`.
LOGIN = {"machine": {"$ref": "machine"}, "username": "root", "password": "a"}
COMMUNICATORS: dict[str, dict[str, Any]] = {
    "serial": {
        "susa.communicator.serial.SerialCommunicator": {
            "machine": {"$ref": "machine"},
            "login": {"username": "root", "password": "a"},
        }
    },
    "ssh": {"susa.communicator.ssh.SSHCommunicator": LOGIN},
    "ssh-scp": {
        "susa.communicator.ssh.SSHCommunicator": {**LOGIN, "file_transfer": "scp"}
    },
    "ssh-shell": {
        "susa.communicator.ssh.SSHCommunicator": {**LOGIN, "file_transfer": "shell"}
    },
    "telnet": {"susa.communicator.telnet.TelnetCommunicator": LOGIN},
    "rlogin": {"susa.communicator.rlogin.RloginCommunicator": LOGIN},
}


def boot(machine: LVMachine) -> None:
    wait_until_booted(machine, BOOT_TIMEOUT, QUIET_TIME)


@pytest.fixture(scope="session")
def connection() -> Iterator[None]:
    with Connection("qemu:///system"):
        yield


# Each image's tests share one worker (see `--dist loadgroup` in pyproject.toml), so it boots once.
@pytest.fixture(
    scope="module",
    params=[pytest.param(n, marks=pytest.mark.xdist_group(n)) for n in IMAGES],
)
def session(request: pytest.FixtureRequest, connection: None) -> Iterator[Session]:
    image = IMAGES[request.param]
    if not image.path.exists():
        pytest.skip(f"{image.path} doesn't exist")
    with Session.parse(image.session()) as session:
        boot(session.get("machine", LVMachine))
        yield session


@pytest.fixture(scope="module")
def ready(session: Session) -> Iterator[LVSnapshot]:
    with session.get("machine", LVMachine).snapshot() as snapshot:
        yield snapshot


# The name (in `IMAGES`) of the machine the test got.
@pytest.fixture
def name(request: pytest.FixtureRequest) -> str:
    result: str = request.node.callspec.params["session"]
    return result


# The machine as it was once it booted, with what its serial console says during the test in the report.
@pytest.fixture
def machine(
    request: pytest.FixtureRequest, session: Session, ready: LVSnapshot
) -> Iterator[LVMachine]:
    machine = session.get("machine", LVMachine)
    with machine.serial() as serial:
        yield machine
        output = serial.read_available().decode(errors="backslashreplace")
        request.node.add_report_section("call", "serial", output)
    ready.revert()


@pytest.fixture
def network(session: Session) -> LVNetwork:
    return session.get("network", LVNetwork)


@pytest.fixture
def volume(session: Session) -> LVVolume:
    return session.get("volume", LVVolume)


def test_ping(machine: LVMachine) -> None:
    assert ping(machine.ip, timeout=5) is not None


def test_screenshot(machine: LVMachine) -> None:
    screenshot = machine.screenshot()
    # PNG or PPM, depending on the QEMU version.
    assert screenshot.data.startswith((b"\x89PNG\r\n\x1a\n", b"P6"))


def test_serial(machine: LVMachine) -> None:
    with machine.serial() as serial:
        # Whatever's on the console (e.g. getty) answers a line.
        serial.write(b"\r")
        assert serial.read(timeout=30)
        serial.wait_until_quiet(QUIET_TIME, 60)

        # Reads stop at `size`, leaving the rest for the next read.
        serial.write(b"\r")
        assert len(serial.read(1, timeout=30)) == 1
        assert serial.read(timeout=30)


def communicator(machine: LVMachine, kind: str) -> ShellCommunicator:
    if shutil.which(CLIENTS.get(kind, "true")) is None:
        pytest.skip(f"There's no {CLIENTS[kind]} client")
    result: ShellCommunicator = make(COMMUNICATORS[kind], machine=machine)
    return result


CLIENTS = {"telnet": "telnet", "rlogin": "rlogin"}
SHELLS = ("serial", "ssh", "telnet", "rlogin")
UNAME = {name: name for name in IMAGES} | {
    # The CPU is i486-class (see `ARCH_DEFAULTS`).
    "i386": "i486",
    "freebsd": "amd64",
    "freebsd10": "amd64",
}


@pytest.mark.parametrize("kind", SHELLS)
def test_uname(machine: LVMachine, name: str, kind: str) -> None:
    with communicator(machine, kind) as c:
        result = c.run("uname -m")
        assert (result.returncode, result.stdout, result.stderr) == (
            0,
            f"{UNAME[name]}\n".encode(),
            b"",
        )


@pytest.mark.parametrize("kind", SHELLS)
def test_run(machine: LVMachine, kind: str) -> None:
    with communicator(machine, kind) as c:
        result = c.run("echo a; echo b >&2; false")
        assert (result.returncode, result.stdout, result.stderr) == (1, b"a\n", b"b\n")
        assert c.execute("cd /tmp; pwd").stdout == b"/tmp\n"
        assert c.execute("pwd").stdout == b"/tmp\n"


@pytest.mark.parametrize("kind", SHELLS)
def test_start(machine: LVMachine, kind: str) -> None:
    with communicator(machine, kind) as c:
        command = c.start("echo started; sleep 2; echo done >&2")
        assert command.stdout.read_until(b"started\n", timeout=10) == b"started\n"
        assert command.poll() is None
        assert command.wait() == 0
        assert command.stderr.read() == b"done\n"


@pytest.mark.parametrize("kind", COMMUNICATORS)
def test_transfer(machine: LVMachine, kind: str, tmp_path: Path) -> None:
    data = [random.randbytes(5000) for _ in range(3)]
    for i, content in enumerate(data):
        (tmp_path / f"up{i}").write_bytes(content)
    with communicator(machine, kind) as c:
        c.upload_single(tmp_path / "up0", "/tmp/susa0")
        c.download_single("/tmp/susa0", tmp_path / "down0")
        c.upload({tmp_path / f"up{i}": f"/tmp/susa{i}" for i in (1, 2)})
        c.download({f"/tmp/susa{i}": tmp_path / f"down{i}" for i in (1, 2)})
    for i, content in enumerate(data):
        assert (tmp_path / f"down{i}").read_bytes() == content


def test_power_cycle(machine: LVMachine) -> None:
    machine.power_off()
    assert not machine.is_powered_on

    machine.power_on()
    assert machine.is_powered_on
    # Booting may take longer than usual while other machines run in parallel.
    wait_until_ping(machine.ip, timeout=2 * BOOT_TIMEOUT)


def test_sniff(machine: LVMachine, network: LVNetwork) -> None:
    with network.sniffer() as sniffer:
        ping(machine.ip, 3, timeout=5, interval=1)
    requests = [
        p
        for p in sniffer.packets()
        if ICMP in p and p[ICMP].type == 8 and p[IP].dst == machine.ip
    ]
    assert len(requests) == 3


# What's written to a machine's volume is kept by committing it, e.g. for another machine to boot from (tried on one,
# small image).
def test_commit(machine: LVMachine, volume: LVVolume, name: str) -> None:
    if name != "freebsd10":
        pytest.skip("Committing is tried on freebsd10")
    with communicator(machine, "ssh") as c:
        c.check("echo committed > /root/susa-commit")
    # Cleanly, so the file system is written out.
    machine.shutdown()
    wait_until(lambda _: not machine.is_powered_on, BOOT_TIMEOUT)
    with (
        volume.commit(VolumeModel()) as committed,
        Session.parse(IMAGES[name].session(Path(committed.path))) as session,
    ):
        copy = session.get("machine", LVMachine)
        boot(copy)
        with communicator(copy, "ssh") as c:
            assert c.check("cat /root/susa-commit") == b"committed\n"
