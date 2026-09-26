"""Tests of the libvirt entities against libvirt's mock driver, which doesn't run anything."""

from __future__ import annotations

from collections.abc import Generator

import libvirt as lv
import pytest

from susa.core.interface import Interface
from susa.core.machine import (
    Machine,
    Powerable,
    Screenshottable,
    SerialAccessible,
    Snapshot,
)
from susa.core.network import Network
from susa.libvirt.connection import Connection
from susa.libvirt.interface import LVInterface
from susa.libvirt.interface_model import InterfaceModel
from susa.libvirt.machine import LVMachine, LVSnapshot
from susa.libvirt.machine_model import MachineModel
from susa.libvirt.network import LVNetwork
from susa.libvirt.network_model import NetworkModel
from susa.utilities.generic import GIGA

MAC = "52:54:00:12:34:56"


@pytest.fixture(autouse=True)
def connection() -> Generator[None, None, None]:
    with Connection("test:///default"):
        yield


def domain(*interfaces: InterfaceModel) -> MachineModel:
    result = MachineModel().arch("x86_64").default().memory(GIGA)
    for interface in interfaces:
        result.interface(interface)
    return result


def test_network() -> None:
    model = NetworkModel().default().ip("10.0.0.1")
    network = LVNetwork(model)
    assert isinstance(network, Network)
    assert network.model is model
    assert network.name == model.get_name()

    with network:
        assert network.value is not None
        assert network.value.name() == network.name
        assert network.value.isActive()
    assert network.value is None


def test_network_interfaces() -> None:
    model = NetworkModel().default().ip("10.0.0.1")
    network = LVNetwork(model)
    assert network.interfaces == []

    model.interface(InterfaceModel(mac=MAC), "10.0.0.10")
    model.interface(InterfaceModel(mac="52:54:00:00:00:01"))

    with network:
        interfaces = network.interfaces
        assert all(isinstance(i, Interface) for i in interfaces)
        assert [(i.mac, i.ip) for i in interfaces] == [
            (MAC, "10.0.0.10"),
            ("52:54:00:00:00:01", "10.0.0.2"),
        ]


def test_network_and_machine_interfaces_match() -> None:
    network = NetworkModel().default().ip("10.0.0.1")
    interface = InterfaceModel(mac=MAC).default("x86_64")
    network.interface(interface)

    with LVNetwork(network) as n, LVMachine(domain(interface), [n]) as m:
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
        assert machine.value is not None
        assert machine.value.name() == machine.name
        assert machine.value.isActive()
        assert machine.interfaces == []
    assert machine.value is None


def test_machine_interfaces() -> None:
    network = NetworkModel().default().ip("10.0.0.1")
    reserved = InterfaceModel(mac=MAC).default("x86_64")
    automatic = InterfaceModel(mac="52:54:00:00:00:01").default("x86_64")
    network.interface(reserved, "10.0.0.10").interface(automatic)

    with (
        LVNetwork(network) as n,
        LVMachine(domain(reserved, automatic), [n]) as machine,
    ):
        interfaces = machine.interfaces
        assert all(isinstance(i, Interface) for i in interfaces)
        assert [(i.mac, i.ip) for i in interfaces] == [
            (MAC, "10.0.0.10"),
            ("52:54:00:00:00:01", "10.0.0.2"),
        ]


def test_interface_without_reservation() -> None:
    # The interface is connected to the network, but the network has no DHCP to reserve an IP with.
    network = NetworkModel().default().ip("10.0.0.1", dhcp=False)
    interface = InterfaceModel(mac=MAC).default("x86_64")
    network.interface(interface)

    with LVNetwork(network) as n, LVMachine(domain(interface), [n]) as machine:
        [result] = machine.interfaces
        assert result.mac == MAC
        assert result.ip is None


def test_machine_interfaces_without_networks() -> None:
    # Without being told about the network, the machine can't know the reserved IP.
    network = NetworkModel().default().ip("10.0.0.1")
    interface = InterfaceModel(mac=MAC).default("x86_64")
    network.interface(interface, "10.0.0.10")

    with LVNetwork(network), LVMachine(domain(interface)) as machine:
        [result] = machine.interfaces
        assert (result.mac, result.ip) == (MAC, None)


def test_interface() -> None:
    interface = LVInterface(MAC, "10.0.0.10")
    assert isinstance(interface, Interface)
    assert (interface.mac, interface.ip) == (MAC, "10.0.0.10")
    assert LVInterface(MAC).ip is None


def test_machine_is_persistent_until_destroyed() -> None:
    machine = LVMachine(domain())
    with machine:
        name = machine.name
        machine.power_off()
        assert not machine.is_powered_on
        # Still defined, so it can be powered on again.
        machine.power_on()
        assert machine.is_powered_on
    assert machine.value is None
    with pytest.raises(lv.libvirtError):
        Connection.current_conn().lookupByName(name)


def test_machine_power() -> None:
    with LVMachine(domain()) as machine:
        assert isinstance(machine, Powerable)
        assert machine.is_powered_on
        machine.reboot()
        assert machine.is_powered_on
        machine.reset()
        assert machine.is_powered_on
        # The mock driver's guests shut down instantly.
        machine.shutdown()
        assert not machine.is_powered_on
        machine.power_on()
        assert machine.is_powered_on


def test_machine_destroy_when_powered_off() -> None:
    machine = LVMachine(domain())
    with machine:
        machine.power_off()
    assert machine.value is None


def test_machine_screenshot() -> None:
    with LVMachine(domain()) as machine:
        assert isinstance(machine, Screenshottable)
        screenshot = machine.screenshot()
        assert screenshot.mime_type == "image/png"
        assert screenshot.data.startswith(b"\x89PNG\r\n\x1a\n")


def test_machine_serial_needs_created_machine() -> None:
    machine = LVMachine(domain())
    assert isinstance(machine, SerialAccessible)
    with pytest.raises(AssertionError):
        machine.serial()


def test_snapshot() -> None:
    with LVMachine(domain()) as machine:
        snapshot = machine.snapshot()
        assert isinstance(snapshot, Snapshot)
        assert isinstance(snapshot, LVSnapshot)
        assert snapshot.machine is machine
        assert snapshot.value is not None
        assert snapshot.value.getName() == snapshot.name
        assert machine.value is not None
        assert [s.getName() for s in machine.value.listAllSnapshots()] == [
            snapshot.name
        ]

        # Destroying reverts, and forgets the snapshot.
        snapshot.destroy()
        assert snapshot.value is None
