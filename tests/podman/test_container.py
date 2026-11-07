from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from scapy.layers.inet import ICMP

from susa.communicators.container import ContainerCommunicator
from susa.communicators.rlogin import RloginCommunicator
from susa.communicators.ssh import SSHCommunicator
from susa.communicators.telnet import TelnetCommunicator
from susa.core.communicator import HOST
from susa.libvirt import (
    URI,
    LVMachine,
    LVMachineModel,
    LVNetwork,
    LVNetworkModel,
    LVVolume,
    LVVolumeModel,
)
from susa.libvirt.arch import host_arch
from susa.podman.container import LibvirtContainer
from susa.utilities.generic import GIGA, wait_until
from susa.utilities.networking import SubnetReservation, pings

IMAGE = Path(f"/machines/debian_{host_arch()}.qcow2")
ENVIRONMENT = ("SUSA_SESSION", "LIBVIRT_DEFAULT_URI", "SUSA_SUBNETS_LOCK")


def needs_podman() -> None:
    if shutil.which("podman") is None or not IMAGE.exists():
        pytest.skip(f"Needs podman and {IMAGE}")


@pytest.fixture
def container() -> Iterator[LibvirtContainer]:
    needs_podman()
    defaults = (HOST.get(), URI.get(), SubnetReservation.LOCK.get())
    environment = [os.environ.get(name) for name in ENVIRONMENT]
    container = LibvirtContainer([str(IMAGE.parent)])
    logging.info("Starting the container")
    with container:
        yield container
    assert (HOST.get(), URI.get(), SubnetReservation.LOCK.get()) == defaults
    assert [os.environ.get(name) for name in ENVIRONMENT] == environment
    exists = ["podman", "container", "exists", container.name]
    assert subprocess.run(exists, check=False).returncode == 1


# Of processes started meanwhile, too.
def test_defaults(container: LibvirtContainer) -> None:
    host = HOST.get()
    assert isinstance(host, ContainerCommunicator)
    code = """
from susa.core.communicator import HOST
from susa.libvirt._virsh import virsh
from susa.utilities.networking import SubnetReservation

print(vars(HOST.get()))
print(SubnetReservation.LOCK.get())
print(virsh("uri").strip())
"""
    output = subprocess.check_output([sys.executable, "-c", code]).decode()
    lock, uri = SubnetReservation.LOCK.get(), URI.get()
    assert output.splitlines() == [str(vars(host)), str(lock), uri]


def test_container(container: LibvirtContainer) -> None:
    with SubnetReservation() as subnet:
        network_model = LVNetworkModel().default().ip(subnet.ip)
        volume_model = LVVolumeModel().backing(IMAGE)
        machine_model = (
            LVMachineModel()
            .arch(host_arch())
            .efi()
            .default()
            .memory(2 * GIGA)
            .volume(volume_model)
            .network(network_model)
        )
        with (
            LVNetwork(network_model) as network,
            LVVolume(volume_model),
            LVMachine(machine_model) as machine,
            SSHCommunicator(machine.ip, "root", "a") as ssh,
        ):
            assert ssh.check("uname -m").decode().strip() == host_arch()
            for shell in (TelnetCommunicator, RloginCommunicator):
                logging.info("Connecting with %s", shell.__name__)
                with shell(machine.ip, "root", "a") as communicator:
                    assert communicator.check("echo up") == b"up\n"
            with network.sniffer() as sniffer:
                _ = sniffer.pcap
                logging.info("Pinging the machine while sniffing its network")
                assert None not in pings(machine.ip, 2, timeout=5, interval=0.5)
                time.sleep(1)
            assert sum(ICMP in packet for packet in sniffer.packets()) >= 4


def sleeping(seconds: int) -> bool:
    command = ["pgrep", "-fx", f"sleep {seconds}"]
    return subprocess.run(command, check=False).returncode == 0


# Commands run in its PID namespace, so they stop with it.
def test_stop() -> None:
    needs_podman()
    with LibvirtContainer([str(IMAGE.parent)]):
        command = HOST.get().start("sleep 3605; true")
        time.sleep(0.5)
        assert sleeping(3605)
    assert command.wait(timeout=10) != 0
    assert not sleeping(3605)


# It's removed when this process ends, even when it's killed.
def test_crash() -> None:
    needs_podman()
    code = f"""
import os, signal
from susa.podman.container import LibvirtContainer
container = LibvirtContainer([{str(IMAGE.parent)!r}])
container.create()
print(container.name, container.directory, flush=True)
os.kill(os.getpid(), signal.SIGKILL)
"""
    output = subprocess.run(
        [sys.executable, "-c", code], check=False, capture_output=True, text=True
    )
    name, directory = output.stdout.split()
    exists = ["podman", "container", "exists", name]
    wait_until(lambda: subprocess.run(exists, check=False).returncode == 1, 60)
    wait_until(lambda: not Path(directory).exists(), 10)
