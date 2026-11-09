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

from susa.communicators.container import ContainerCommunicator
from susa.core.communicator import HOST
from susa.libvirt import (
    LVURI,
)
from susa.libvirt.arch import host_arch
from susa.podman.container import LibvirtContainer
from susa.utilities.generic import wait_until
from susa.utilities.networking import SubnetReservation

IMAGE = Path(f"/machines/debian_{host_arch()}.qcow2")
ENVIRONMENT = ("SUSA_HOST", "SUSA_LVURI", "SUSA_SUBNETS_LOCK")


def needs_podman() -> None:
    if shutil.which("podman") is None or not IMAGE.exists():
        pytest.skip(f"Needs podman and {IMAGE}")


@pytest.fixture
def container() -> Iterator[LibvirtContainer]:
    needs_podman()
    defaults = (HOST.get(), LVURI.get(), SubnetReservation.LOCK.get())
    environment = [os.environ.get(name) for name in ENVIRONMENT]
    container = LibvirtContainer([str(IMAGE.parent)])
    logging.info("Starting the container")
    with container:
        yield container
    assert (HOST.get(), LVURI.get(), SubnetReservation.LOCK.get()) == defaults
    assert [os.environ.get(name) for name in ENVIRONMENT] == environment
    exists = ["podman", "container", "exists", container.name]
    assert subprocess.run(exists, check=False).returncode == 1


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
    lock, uri = SubnetReservation.LOCK.get(), LVURI.get()
    assert output.splitlines() == [str(vars(host)), str(lock), uri]


def sleeping(seconds: int) -> bool:
    command = ["pgrep", "-fx", f"sleep {seconds}"]
    return subprocess.run(command, check=False).returncode == 0


def test_stop() -> None:
    needs_podman()
    with LibvirtContainer([str(IMAGE.parent)]):
        command = HOST.get().start("sleep 3605; true")
        time.sleep(0.5)
        assert sleeping(3605)
    assert command.wait(timeout=10) != 0
    assert not sleeping(3605)


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


def test_create_fails() -> None:
    needs_podman()
    defaults = (HOST.get(), LVURI.get(), SubnetReservation.LOCK.get())
    container = LibvirtContainer(start_timeout=0)
    with pytest.raises(TimeoutError):
        container.create()
    assert (HOST.get(), LVURI.get(), SubnetReservation.LOCK.get()) == defaults
    exists = ["podman", "container", "exists", container.name]
    assert subprocess.run(exists, check=False).returncode == 1
