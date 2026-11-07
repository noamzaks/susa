from __future__ import annotations

import contextlib
import json
import logging
import os
import random
import shutil
import subprocess
import time
from collections.abc import Callable, Generator, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from scapy.layers.inet import ICMP, IP

from susa.communicators.shell import ShellCommunicator
from susa.communicators.unix import UnixCommunicator
from susa.core.communicator import FileTransferrer
from susa.core.machine import wait_until_booted
from susa.core.resource import Resource
from susa.core.saveable import SavedResources, save
from susa.libvirt import (
    LVMachine,
    LVNetwork,
    LVSnapshot,
    LVVolume,
    LVVolumeModel,
)
from susa.libvirt._virsh import LVURI, virsh
from susa.recipes import Recipe
from susa.recipes.session import Session
from susa.utilities.generic import GIGA, wait_until
from susa.utilities.networking import ping, pings

MACHINES = Path("/machines")
MACHINE_MODEL = "susa.libvirt.machine_model.LVMachineModel"
NETWORK_MODEL = "susa.libvirt.network_model.LVNetworkModel"
VOLUME_MODEL = "susa.libvirt.volume_model.LVVolumeModel"
SUBNET = "susa.utilities.networking.SubnetReservation"
LV_NETWORK = "susa.libvirt.network.LVNetwork"
LV_VOLUME = "susa.libvirt.volume.LVVolume"
LV_MACHINE = "susa.libvirt.machine.LVMachine"
BOOT_TIMEOUT = 300
QUIET_TIME = 5


# A base image, and the steps of the machine's recipe for it (setting it up for its architecture, with 2 GB).
@dataclass(frozen=True)
class Image:
    path: Path
    steps: list[Any]

    def session(self, path: Path | None = None) -> list[dict[str, Any]]:
        machine = [
            *self.steps,
            "default",
            {"memory": 2 * GIGA},
            {"volume": {"$ref": "volume_model"}},
            {"network": {"$ref": "network_model"}},
        ]
        return [
            {"subnet": {SUBNET: {}}},
            {
                "network_model": {
                    NETWORK_MODEL: ["default", {"ip": {"$ref": "subnet.ip"}}]
                }
            },
            {
                "volume_model": {
                    VOLUME_MODEL: [{"backing": str(path or self.path)}, "default"]
                }
            },
            {"machine_model": {MACHINE_MODEL: machine}},
            {"network": {LV_NETWORK: {"model": {"$ref": "network_model"}}}},
            {"volume": {LV_VOLUME: {"model": {"$ref": "volume_model"}}}},
            {"machine": {LV_MACHINE: {"model": {"$ref": "machine_model"}}}},
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
LOGIN = {"ip": {"$ref": "machine.ip"}, "username": "root", "password": "a"}
COMMUNICATORS: dict[str, dict[str, Any]] = {
    "serial": {
        "susa.communicators.serial.SerialCommunicator": {
            "machine": {"$ref": "machine"},
            "login": {"username": "root", "password": "a"},
        }
    },
    "ssh": {"susa.communicators.ssh.SSHCommunicator": LOGIN},
    "ssh-scp": {
        "susa.communicators.ssh.SSHCommunicator": {**LOGIN, "file_transfer": "scp"}
    },
    "telnet": {"susa.communicators.telnet.TelnetCommunicator": LOGIN},
    "rlogin": {"susa.communicators.rlogin.RloginCommunicator": LOGIN},
}


def boot(machine: LVMachine) -> None:
    wait_until_booted(machine, BOOT_TIMEOUT, QUIET_TIME)


@pytest.fixture(scope="session")
def uri() -> Iterator[None]:
    with LVURI.set("qemu:///system"):
        yield


# Each image's tests share one worker (see `--dist loadgroup` in pyproject.toml), so it boots once.
@pytest.fixture(
    scope="module",
    params=[pytest.param(n, marks=pytest.mark.xdist_group(n)) for n in IMAGES],
)
def name(request: pytest.FixtureRequest) -> str:
    result: str = request.param
    return result


@pytest.fixture(scope="module")
def session(name: str, uri: None) -> Iterator[Session]:
    image = IMAGES[name]
    if not image.path.exists():
        pytest.skip(f"{image.path} doesn't exist")
    with Session.model_validate({"objects": image.session()}) as session:
        boot(session.get("machine", LVMachine))
        yield session


@pytest.fixture(scope="module")
def ready(session: Session) -> Iterator[LVSnapshot]:
    logging.info("Snapshotting the booted machine")
    with session.get("machine", LVMachine).snapshot() as snapshot:
        yield snapshot


@pytest.fixture
def machine(
    session: Session,
    ready: LVSnapshot,
    save_if_failed: Callable[[Sequence[Resource]], None],
) -> Iterator[LVMachine]:
    yield session.get("machine", LVMachine)
    save_if_failed(session.all(Resource))
    logging.info("Reverting the machine to its snapshot")
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


@contextlib.contextmanager
def shell(machine: LVMachine, kind: str) -> Generator[ShellCommunicator, None, None]:
    if shutil.which(CLIENTS.get(kind, "true")) is None:
        pytest.skip(f"There's no {CLIENTS[kind]} client")
    result: ShellCommunicator = Recipe.model_validate(COMMUNICATORS[kind]).make(
        machine=machine
    )
    logging.info("Connecting over %s", kind)
    with result:
        yield result


@contextlib.contextmanager
def unix(machine: LVMachine, kind: str) -> Generator[UnixCommunicator, None, None]:
    with shell(machine, kind) as communicator, UnixCommunicator(communicator) as u:
        yield u


@contextlib.contextmanager
def transferrer(
    machine: LVMachine, kind: str
) -> Generator[FileTransferrer, None, None]:
    if kind in ("ssh", "ssh-scp"):
        with shell(machine, kind) as ssh:
            assert isinstance(ssh, FileTransferrer)
            yield ssh
    else:
        with unix(machine, kind.removesuffix("-unix")) as u:
            yield u


CLIENTS = {"telnet": "telnet", "rlogin": "rlogin"}
SHELLS = ("serial", "ssh", "telnet", "rlogin")
TRANSFERRERS = ("serial", "ssh", "ssh-scp", "ssh-unix", "telnet", "rlogin")
UNAME = {name: name for name in IMAGES} | {
    # The CPU is i486-class (see `ARCH_DEFAULTS`).
    "i386": "i486",
    "freebsd": "amd64",
    "freebsd10": "amd64",
}


@pytest.mark.parametrize("kind", SHELLS)
def test_uname(machine: LVMachine, name: str, kind: str) -> None:
    with unix(machine, kind) as u:
        result = u.run("uname -m")
        assert (result.returncode, result.stdout, result.stderr) == (
            0,
            f"{UNAME[name]}\n".encode(),
            b"",
        )


@pytest.mark.parametrize("kind", SHELLS)
def test_run(machine: LVMachine, kind: str) -> None:
    with unix(machine, kind) as u:
        result = u.run("echo a; echo b >&2; false")
        assert (result.returncode, result.stdout, result.stderr) == (1, b"a\n", b"b\n")
        assert u.communicator.check("cd /tmp; pwd") == b"/tmp\n"
        assert u.communicator.check("pwd") == b"/tmp\n"


@pytest.mark.parametrize("kind", SHELLS)
def test_start(machine: LVMachine, kind: str) -> None:
    with unix(machine, kind) as u:
        command = u.start("echo started; sleep 2; echo done >&2")
        assert command.stdout.read_until(b"started\n", timeout=10) == b"started\n"
        assert command.poll() is None
        assert command.wait() == 0
        assert command.stderr.read() == b"done\n"


# What it started stops when its shell disconnects.
@pytest.mark.parametrize("kind", SHELLS)
def test_disconnect(machine: LVMachine, kind: str) -> None:
    # Unlike its own command line.
    sleeping = "pgrep -f '[s]leep 3606'"
    with unix(machine, kind) as u:
        u.start("sleep 3606; true")
        wait_until(lambda: u.communicator.run(sleeping).returncode == 0, 10)
    with shell(machine, "ssh") as ssh:
        wait_until(lambda: ssh.run(sleeping).returncode == 1, 10)


@pytest.mark.parametrize("kind", TRANSFERRERS)
def test_transfer(machine: LVMachine, kind: str, tmp_path: Path) -> None:
    data = [random.randbytes(5000) for _ in range(3)]
    for i, content in enumerate(data):
        (tmp_path / f"up{i}").write_bytes(content)
    with transferrer(machine, kind) as t:
        logging.info("Transferring a file each way")
        t.upload_single(tmp_path / "up0", "/tmp/susa0")
        t.download_single("/tmp/susa0", tmp_path / "down0")
        logging.info("Transferring two files each way")
        t.upload({tmp_path / f"up{i}": f"/tmp/susa{i}" for i in (1, 2)})
        t.download({f"/tmp/susa{i}": tmp_path / f"down{i}" for i in (1, 2)})
    for i, content in enumerate(data):
        assert (tmp_path / f"down{i}").read_bytes() == content


# Communicators connect (again) until the machine is up, so they need no waiting for it to boot.
@pytest.mark.parametrize("kind", ("serial", "ssh"))
def test_power_cycle(machine: LVMachine, kind: str) -> None:
    logging.info("Powering the machine off")
    machine.power_off()
    assert not machine.is_powered_on

    logging.info("Powering the machine on")
    machine.power_on()
    assert machine.is_powered_on
    with shell(machine, kind) as s:
        assert s.check("echo up") == b"up\n"


def test_sniff(machine: LVMachine, network: LVNetwork) -> None:
    with network.sniffer() as sniffer:
        # Opening it waits for the header, which tcpdump writes once it's capturing.
        _ = sniffer.pcap
        logging.info("Pinging the machine while sniffing its network")
        pings(machine.ip, 3, timeout=5, interval=1)
        time.sleep(1)
    requests = [
        p
        for p in sniffer.packets()
        if ICMP in p and p[ICMP].type == 8 and p[IP].dst == machine.ip
    ]
    assert len(requests) == 3


# Where QEMU can read it.
@pytest.fixture
def committed() -> Iterator[Path]:
    path = MACHINES / f"susa-committed-{os.getpid()}.qcow2"
    yield path
    path.unlink(missing_ok=True)


# What's written to a machine's volume is kept by committing it, e.g. for another machine to boot from (tried on one,
# small image).
def test_commit(
    machine: LVMachine, volume: LVVolume, name: str, committed: Path
) -> None:
    if name != "freebsd10":
        pytest.skip("Committing is tried on freebsd10")
    with shell(machine, "ssh") as ssh:
        ssh.check("echo committed > /root/susa-commit")
    logging.info("Shutting the machine down")
    # Cleanly, so the file system is written out.
    machine.shutdown()
    wait_until(lambda: not machine.is_powered_on, BOOT_TIMEOUT)
    logging.info("Committing its volume into %s", committed)
    volume.commit(str(committed))
    recipe = [*IMAGES[name].session(committed), {"ssh": COMMUNICATORS["ssh"]}]
    logging.info("Booting a machine from the committed image")
    with Session.model_validate({"objects": recipe}) as session:
        ssh = session.get("ssh", ShellCommunicator)
        assert ssh.check("cat /root/susa-commit") == b"committed\n"


# A machine comes back as it was saved, running and with what it wrote, once its resources are gone (tried on one,
# small image).
def test_save(name: str, uri: None, tmp_path: Path) -> None:
    if name != "freebsd10":
        pytest.skip("Saving is tried on freebsd10")
    with Session.model_validate({"objects": IMAGES[name].session()}) as session:
        boot(session.get("machine", LVMachine))
        with shell(session.get("machine", LVMachine), "ssh") as ssh:
            ssh.check("echo saved > /root/susa-save")
            booted = ssh.check("sysctl -n kern.boottime")
        logging.info("Saving the machine")
        saved = json.dumps(save(session.all(Resource)))
    logging.info("Restoring the machine")
    with SavedResources(json.loads(saved)) as restored:
        [machine] = [r for r in restored.resources if isinstance(r, LVMachine)]
        with shell(machine, "ssh") as ssh:
            assert ssh.check("cat /root/susa-save") == b"saved\n"
            assert ssh.check("sysctl -n kern.boottime") == booted


def qemu(*args: str | Path) -> None:
    subprocess.run(args, check=True, capture_output=True)


# Committing into the image backing a volume, which here is a small one of its own (others would see the change).
def test_commit_into_backing(uri: None, tmp_path: Path) -> None:
    image = tmp_path / "image.qcow2"
    qemu("qemu-img", "create", "-f", "qcow2", image, "1M")
    with LVVolume(LVVolumeModel().backing(image).default()) as volume:
        # What a machine would have written to it.
        written = tmp_path / "written.qcow2"
        qemu("qemu-img", "create", "-f", "qcow2", "-b", image, "-F", "qcow2", written)
        qemu("qemu-io", "-c", "write -P 0xab 0 4k", written)
        virsh(
            "vol-upload",
            "--pool",
            volume.model.get_pool(),
            volume.model.get_name(),
            str(written),
        )

        volume.commit()
    qemu("qemu-io", "-c", "read -P 0xab 0 4k", image)
