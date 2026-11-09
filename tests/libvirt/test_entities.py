from __future__ import annotations

import pickle
import signal
import subprocess
import sys
from typing import Any

import pytest

from susa.core.interface import Interface
from susa.core.keyboard import Key, KeyPressable
from susa.core.machine import (
    Machine,
    Powerable,
    Screenshottable,
    Snapshot,
)
from susa.core.network import Network
from susa.libvirt._virsh import virsh
from susa.libvirt.disk_model import LVDiskModel
from susa.libvirt.entity import LVEntity
from susa.libvirt.interface_model import LVInterfaceModel
from susa.libvirt.machine import (
    LVMachine,
    LVSnapshot,
)
from susa.libvirt.machine_model import LVMachineModel
from susa.libvirt.network import LVNetwork
from susa.libvirt.network_model import LVNetworkModel
from susa.libvirt.volume import LVVolume
from susa.libvirt.volume_model import LVVolumeModel
from susa.utilities.generic import GIGA, wait_until

MAC = "52:54:00:12:34:56"


pytestmark = [
    pytest.mark.usefixtures("libvirt"),
    pytest.mark.xdist_group("test_entities"),
]


def domain(*interfaces: LVInterfaceModel) -> LVMachineModel:
    result = LVMachineModel().arch("x86_64").default().memory(GIGA // 4)
    for interface in interfaces:
        result.interface(interface)
    return result


def test_network() -> None:
    model = LVNetworkModel().default().ip("10.0.0.1")
    network = LVNetwork(model)
    assert isinstance(network, Network)
    assert network.model is model
    assert network.name == model.get_name()

    with network:
        assert network.name in virsh("net-list", "--name")
    assert network.name not in virsh("net-list", "--name")


def test_network_interfaces() -> None:
    model = LVNetworkModel().default().ip("10.0.0.1")
    network = LVNetwork(model)
    assert network.interfaces == []

    model.interface(LVInterfaceModel(mac=MAC), "10.0.0.10")
    model.interface(LVInterfaceModel(mac="52:54:00:00:00:01"))

    with network:
        interfaces = network.interfaces
        assert all(isinstance(i, Interface) for i in interfaces)
        assert [(i.mac, i.ip) for i in interfaces] == [
            (MAC, "10.0.0.10"),
            ("52:54:00:00:00:01", "10.0.0.2"),
        ]


def test_network_and_machine_interfaces_match() -> None:
    network = LVNetworkModel().default().ip("10.0.0.1")
    interface = LVInterfaceModel(mac=MAC)
    network.interface(interface)

    with LVNetwork(network) as n, LVMachine(domain(interface)) as m:
        assert [(i.mac, i.ip) for i in n.interfaces] == [
            (i.mac, i.ip) for i in m.interfaces
        ]


def test_machine() -> None:
    model = domain()
    machine = LVMachine(model)
    assert isinstance(machine, Machine)
    assert machine.model is model
    assert machine.name == model.get_name()

    with machine:
        assert machine.is_powered_on
        assert machine.interfaces == []


def test_machine_interfaces() -> None:
    network = LVNetworkModel().default().ip("10.0.0.1")
    reserved = LVInterfaceModel(mac=MAC)
    automatic = LVInterfaceModel(mac="52:54:00:00:00:01")
    network.interface(reserved, "10.0.0.10").interface(automatic)

    with (
        LVNetwork(network),
        LVMachine(domain(reserved, automatic)) as machine,
    ):
        interfaces = machine.interfaces
        assert all(isinstance(i, Interface) for i in interfaces)
        assert [(i.mac, i.ip) for i in interfaces] == [
            (MAC, "10.0.0.10"),
            ("52:54:00:00:00:01", "10.0.0.2"),
        ]


def test_interface_without_reservation() -> None:
    network = LVNetworkModel().default().ip("10.0.0.1", dhcp=False)
    interface = LVInterfaceModel(mac=MAC)
    network.interface(interface)

    with LVNetwork(network), LVMachine(domain(interface)) as machine:
        [result] = machine.interfaces
        assert result.mac == MAC
        assert result.ip is None


def test_machine_is_persistent_until_destroyed() -> None:
    machine = LVMachine(domain())
    with machine:
        name = machine.name
        machine.power_off()
        assert not machine.is_powered_on
        machine.power_on()
        assert machine.is_powered_on
    with pytest.raises(subprocess.CalledProcessError):
        virsh("dominfo", name)


def test_machine_power() -> None:
    with LVMachine(domain()) as machine:
        assert isinstance(machine, Powerable)
        assert machine.is_powered_on
        machine.reboot()
        assert machine.is_powered_on
        machine.reset()
        assert machine.is_powered_on
        machine.power_off()
        assert not machine.is_powered_on
        machine.power_on()
        assert machine.is_powered_on


def test_machine_destroy_when_powered_off() -> None:
    machine = LVMachine(domain())
    with machine:
        machine.power_off()


def test_machine_screenshot() -> None:
    with LVMachine(domain()) as machine:
        assert isinstance(machine, Screenshottable)
        screenshot = machine.screenshot()
        assert screenshot.mime_type == "image/png"
        assert screenshot.data.startswith(b"\x89PNG\r\n\x1a\n")


def test_snapshot() -> None:
    volume = LVVolumeModel().capacity(GIGA)
    with LVVolume(volume), LVMachine(domain().volume(volume)) as machine:
        snapshot = machine.snapshot()
        assert isinstance(snapshot, Snapshot)
        assert isinstance(snapshot, LVSnapshot)
        assert snapshot.machine is machine
        snapshot.create()

        snapshot.destroy()
        assert virsh("snapshot-list", machine.name, "--name").strip() == ""


def test_snapshot_context() -> None:
    volume = LVVolumeModel().capacity(GIGA)
    with LVVolume(volume), LVMachine(domain().volume(volume)) as machine:
        with machine.snapshot():
            machine.power_off()
        assert machine.is_powered_on


def test_machine_press() -> None:
    with LVMachine(domain()) as machine:
        assert isinstance(machine, KeyPressable)
        machine.press([Key.LEFT_CTRL, Key.LEFT_ALT, Key.DELETE])
        machine.type_text("root\n")


def test_volume() -> None:
    model = LVVolumeModel().capacity(GIGA)
    with LVVolume(model):
        assert model.get_name() in virsh("vol-list", "default")
    assert model.get_name() not in virsh("vol-list", "default")


def test_machine_volume() -> None:
    volume = LVVolumeModel().capacity(GIGA)
    model = domain().disk(LVDiskModel().volume(volume))
    with LVVolume(volume), LVMachine(model) as machine:
        assert machine.is_powered_on


def test_pickle() -> None:
    network = LVNetwork(LVNetworkModel().default().ip("10.0.0.1"))
    volume_model = LVVolumeModel().capacity(GIGA)
    volume = LVVolume(volume_model)
    machine = LVMachine(domain().volume(volume_model))
    snapshot = machine.snapshot()
    entities: list[LVEntity[Any]] = [network, volume, machine, snapshot]
    for entity, copy in zip(entities, pickle.loads(pickle.dumps(entities))):
        assert copy.model == entity.model


def test_machine_create_fails() -> None:
    machine = LVMachine(domain().volume(LVVolumeModel()))
    with pytest.raises(subprocess.CalledProcessError):
        machine.create()
    assert machine.name not in virsh("list", "--all", "--name")


CRASH = """
import os, signal
from susa.libvirt import LVMachine, LVMachineModel, LVNetwork, LVNetworkModel, LVVolume, LVVolumeModel
from susa.utilities.generic import GIGA

network = LVNetwork(LVNetworkModel().default().ip("10.0.0.1"))
network.create()
volume = LVVolumeModel().capacity(GIGA)
volume_entity = LVVolume(volume)
volume_entity.create()
model = LVMachineModel().arch("x86_64").default().memory(GIGA // 4).volume(volume)
machine = LVMachine(model)
machine.create()
snapshot = machine.snapshot()
snapshot.create()
print(network.name, volume.get_name(), machine.name, flush=True)
os.kill(os.getpid(), signal.SIGKILL)
"""


def test_crash() -> None:
    result = subprocess.run(
        [sys.executable, "-c", CRASH], capture_output=True, text=True, check=False
    )
    assert result.returncode == -signal.SIGKILL, result.stderr
    names = result.stdout.split()
    assert len(names) == 3

    def listed() -> str:
        networks = virsh("net-list", "--all", "--name")
        return (
            networks + virsh("vol-list", "default") + virsh("list", "--all", "--name")
        )

    wait_until(lambda: not any(name in listed() for name in names), 60)
