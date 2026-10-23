from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
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
    Connection,
    LVMachine,
    LVNetwork,
    LVVolume,
    MachineModel,
    NetworkModel,
    VolumeModel,
)
from susa.libvirt.arch import host_arch
from susa.podman.container import LibvirtContainer
from susa.utilities.generic import GIGA
from susa.utilities.networking import SubnetReservation, pings

IMAGE = Path(f"/machines/debian_{host_arch()}.qcow2")
ENVIRONMENT = ("SUSA_SESSION", "LIBVIRT_DEFAULT_URI", "SUSA_SUBNETS_LOCK")


@pytest.fixture
def container() -> Iterator[LibvirtContainer]:
    if shutil.which("podman") is None or not IMAGE.exists():
        pytest.skip(f"Needs podman and {IMAGE}")
    defaults = (HOST.get(), Connection.URI.get(), SubnetReservation.LOCK.get())
    environment = [os.environ.get(name) for name in ENVIRONMENT]
    container = LibvirtContainer([str(IMAGE.parent)])
    logging.info("Starting the container")
    with container:
        yield container
    assert (HOST.get(), Connection.URI.get(), SubnetReservation.LOCK.get()) == defaults
    assert [os.environ.get(name) for name in ENVIRONMENT] == environment
    exists = ["podman", "container", "exists", container.name]
    assert subprocess.run(exists, check=False).returncode == 1


# Of processes started meanwhile, too.
def test_defaults(container: LibvirtContainer) -> None:
    host = HOST.get()
    assert isinstance(host, ContainerCommunicator)
    code = """
from susa.core.communicator import HOST
from susa.libvirt import Connection
from susa.utilities.networking import SubnetReservation

print(vars(HOST.get()))
print(SubnetReservation.LOCK.get())
with Connection() as connection:
    print(connection.conn.getURI())
"""
    output = subprocess.check_output([sys.executable, "-c", code]).decode()
    lock, uri = SubnetReservation.LOCK.get(), Connection.URI.get()
    assert output.splitlines() == [str(vars(host)), str(lock), uri]


def test_container(container: LibvirtContainer) -> None:
    with Connection(), SubnetReservation() as subnet:
        network_model = NetworkModel().default().ip(subnet.ip)
        volume_model = VolumeModel().backing(IMAGE)
        machine_model = (
            MachineModel()
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
                logging.info("Pinging the machine while sniffing its network")
                assert None not in pings(machine.ip, 2, timeout=5, interval=0.5)
            assert sum(ICMP in packet for packet in sniffer.packets()) >= 4
