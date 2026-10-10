from __future__ import annotations

import multiprocessing
import os
import shutil
import subprocess
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pytest

from susa.communicator.ssh import SSHCommunicator
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
from susa.utilities.networking import SubnetReservation

IMAGE = Path(f"/machines/debian_{host_arch()}.qcow2")


def boot() -> tuple[str, LibvirtContainer]:
    # Its event loop stops with it, so the process has a single thread again.
    with Connection("test:///default"):
        pass
    environment = dict(os.environ)
    container = LibvirtContainer([str(IMAGE.parent)])
    with container, Connection(), SubnetReservation() as subnet:
        network_model = NetworkModel().default().ip(subnet.address)
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
            LVNetwork(network_model),
            LVVolume(volume_model),
            LVMachine(machine_model) as machine,
            SSHCommunicator(machine.ip, "root", "a") as ssh,
        ):
            directory = container.directory
            arch = ssh.check("uname -m").decode().strip()
    assert dict(os.environ) == environment
    assert directory is not None and not directory.exists()
    return arch, container


# In a new process, as only a single-threaded one can join the container's user namespace.
def test_container() -> None:
    if shutil.which("podman") is None or not IMAGE.exists():
        pytest.skip(f"Needs podman and {IMAGE}")
    with ProcessPoolExecutor(1, multiprocessing.get_context("spawn")) as pool:
        arch, container = pool.submit(boot).result()
    assert arch == host_arch()
    exists = ["podman", "container", "exists", container.name]
    assert subprocess.run(exists, check=False).returncode == 1
