from __future__ import annotations

import subprocess
from collections.abc import Iterator
from dataclasses import dataclass

import pytest

from susa.communicators.login import Login
from susa.communicators.serial import SerialCommunicator
from susa.core.machine import wait_until_booted
from susa.kubevirt import (
    KVMachine,
    KVMachineModel,
    KVNetwork,
    KVNetworkModel,
    KVVolume,
    KVVolumeModel,
)
from susa.kubevirt._kubectl import kubectl
from susa.kubevirt.emulation import aarch64_without_kvm_script
from susa.utilities.generic import GIGA
from tests.kubevirt.test_machine import (
    BOOT_TIMEOUT,
    GOLDEN,
    GUEST_IP,
    HOST_IP,
    STORAGE_CLASS,
)
from tests.kubevirt.test_machine import golden as golden
from tests.libvirt.test_machine import test_ping as test_ping
from tests.libvirt.test_machine import test_power_cycle as test_power_cycle
from tests.libvirt.test_machine import test_run as test_run
from tests.libvirt.test_machine import test_screenshot as test_screenshot
from tests.libvirt.test_machine import test_serial as test_serial
from tests.libvirt.test_machine import test_sniff as test_sniff
from tests.libvirt.test_machine import test_start as test_start
from tests.libvirt.test_machine import test_transfer as test_transfer
from tests.libvirt.test_machine import test_uname as test_uname

PREPARE = f"""
interface=$(ls /sys/class/net | grep -v lo)
sed -i -E "s/^(allow-hotplug|iface) (ens|enp|eth)[^ ]*/\\1 $interface/" /etc/network/interfaces
ifup $interface
echo {HOST_IP} node >> /etc/hosts
sync
(sleep 2; systemctl restart 'serial-getty@*') > /dev/null 2>&1 &
"""
KERNELS = "localhost:5000/debian-kernel"


@dataclass(frozen=True)
class Guest:
    golden: str
    emulate: str | None = None
    cross_architecture: str | None = None
    efi: bool = False
    cpu: int = 2
    capacity: int = 11 * GIGA
    cmdline: str | None = None
    nic: str | None = None
    pci_address: str | None = None


GUESTS = {
    "aarch64": Guest(GOLDEN),
    "x86_64": Guest("debian-x86-64", cross_architecture="amd64", efi=True),
    "i386": Guest("debian-i386", emulate="i686"),
    "ppc64le": Guest("debian-ppc64le", emulate="ppc64le"),
    "riscv64": Guest(
        "debian-riscv64",
        emulate="riscv64",
        cmdline="root=/dev/vda3 rw console=tty0 console=ttyS0",
    ),
    "armv7l": Guest(
        "debian-armv7l",
        emulate="armv7l",
        cpu=1,
        cmdline="root=/dev/vda1 rw console=tty0 console=ttyAMA0 net.ifnames=0",
    ),
    "mips": Guest(
        "debian-mips",
        emulate="mips",
        cpu=1,
        capacity=18 * GIGA,
        cmdline="root=/dev/sda1 console=tty0 console=ttyS0",
        nic="e1000",
        pci_address="0000:00:0b.0",
    ),
}


@pytest.fixture(scope="module", params=list(GUESTS))
def name(request: pytest.FixtureRequest) -> str:
    result: str = request.param
    try:
        kubectl("get", "datavolume", GUESTS[result].golden)
    except subprocess.CalledProcessError:
        pytest.skip(f"Needs the {GUESTS[result].golden} DataVolume")
    return result


@pytest.fixture(scope="module")
def network(name: str) -> Iterator[KVNetwork]:
    with KVNetwork(KVNetworkModel().ip(HOST_IP)) as network:
        yield network


@pytest.fixture(scope="module")
def running(name: str, network: KVNetwork) -> Iterator[KVMachine]:
    guest = GUESTS[name]
    volume = (
        KVVolumeModel()
        .capacity(guest.capacity)
        .storage_class(STORAGE_CLASS)
        .clone(guest.golden)
    )
    model = KVMachineModel().cpu(guest.cpu).memory(2 * GIGA).volume(volume)
    if guest.emulate is not None:
        model.emulate(guest.emulate)
    elif guest.cross_architecture is not None:
        model.cross_architecture(guest.cross_architecture)
    else:
        model.hook(aarch64_without_kvm_script())
    if guest.efi:
        model.efi()
    if guest.cmdline is not None:
        model.kernel(f"{KERNELS}:{name}", "/kernel", "/initrd", guest.cmdline)
    model.network(network.model, GUEST_IP, guest.nic, guest.pci_address)
    with KVVolume(volume) as created:
        created.wait_until_ready()
        with KVMachine(model, timeout=BOOT_TIMEOUT) as machine:
            machine.wait_until_running()
            with SerialCommunicator(machine, Login("a", "root")) as serial:
                serial.check(PREPARE, timeout=300)
            yield machine


@pytest.fixture
def machine(running: KVMachine) -> KVMachine:
    wait_until_booted(running, BOOT_TIMEOUT)
    return running


@pytest.fixture(autouse=True)
def skip_screenshot(name: str, request: pytest.FixtureRequest) -> None:
    if request.function is test_screenshot and GUESTS[name].cross_architecture:
        pytest.skip("KubeVirt's cross-architecture guests have no video device")
