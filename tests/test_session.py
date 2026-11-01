from __future__ import annotations

import subprocess
from typing import Any

import pydantic
import pytest

from susa.core.machine import Snapshottable, SnapshottableGroup
from susa.libvirt import LVMachine, LVMachineModel, LVNetwork, LVVolume
from susa.libvirt._virsh import virsh
from susa.recipes.session import Session
from susa.utilities.generic import GIGA
from susa.utilities.networking import SubnetReservation

MACHINE = "susa.libvirt.machine_model.LVMachineModel"
NETWORK = "susa.libvirt.network_model.LVNetworkModel"
VOLUME = "susa.libvirt.volume_model.LVVolumeModel"
SUBNET = "susa.utilities.networking.SubnetReservation"
LV_NETWORK = "susa.libvirt.network.LVNetwork"
LV_VOLUME = "susa.libvirt.volume.LVVolume"
LV_MACHINE = "susa.libvirt.machine.LVMachine"


def machine_model(*steps: Any) -> dict[str, Any]:
    return {MACHINE: [{"arch": "x86_64"}, "default", {"memory": GIGA}, *steps]}


SESSION: list[dict[str, Any]] = [
    {"subnet": {SUBNET: {}}},
    {"network_model": {NETWORK: ["default", {"ip": {"$ref": "subnet.ip"}}]}},
    {"volume_model": {VOLUME: [{"capacity": GIGA}]}},
    {
        "machine_model": machine_model(
            {"volume": {"$ref": "volume_model"}},
            {"network": {"$ref": "network_model"}},
        )
    },
    {"network": {LV_NETWORK: {"model": {"$ref": "network_model"}}}},
    {"volume": {LV_VOLUME: {"model": {"$ref": "volume_model"}}}},
    {"machine": {LV_MACHINE: {"model": {"$ref": "machine_model"}}}},
    {"named": {MACHINE: [{"name": {"$ref": "machine.ip"}}]}},
]


pytestmark = [
    pytest.mark.usefixtures("libvirt"),
    pytest.mark.xdist_group("test_session"),
]


def test_session() -> None:
    session = Session.model_validate({"objects": SESSION})
    with session:
        network = session.get("network", LVNetwork)
        machine = session.get("machine", LVMachine)
        volume = session.get("volume", LVVolume)
        assert volume.model.get_name() in virsh("vol-list", "default")
        assert machine.is_powered_on
        [interface] = machine.model.get_interfaces()
        assert interface.get_network() == network.name
        # Made once the machine's created.
        assert session.get("named", LVMachineModel).get_name() == machine.ip
        with pytest.raises(AssertionError):
            session.get("volume", LVMachine)
    assert machine.name not in virsh("list", "--all", "--name")
    assert session.get("subnet", SubnetReservation).subnet is None


def test_session_unique_names() -> None:
    with pytest.raises(pydantic.ValidationError):
        Session.model_validate(
            {"objects": [{"a": {MACHINE: []}}, {"a": {MACHINE: []}}]}
        )


def test_session_refers_back() -> None:
    session = Session.model_validate(
        {
            "objects": [
                {"early": {MACHINE: [{"name": {"$ref": "machine.ip"}}]}},
                *SESSION,
            ]
        }
    )
    with pytest.raises(ValueError):
        session.create()


def test_session_create_fails() -> None:
    network = {LV_NETWORK: {"model": {NETWORK: ["default", {"ip": "10.0.0.1"}]}}}
    volume = {LV_VOLUME: {"model": {VOLUME: [{"pool": "nothing"}]}}}
    session = Session.model_validate(
        {"objects": [{"network": network}, {"volume": volume}]}
    )
    with pytest.raises(subprocess.CalledProcessError):
        session.create()
    assert session.get("network", LVNetwork).name not in virsh("net-list", "--name")


def test_session_snapshot() -> None:
    objects: list[dict[str, Any]] = []
    for name in "ab":
        objects += [
            {f"{name}_model": {VOLUME: [{"capacity": GIGA}]}},
            {f"{name}_volume": {LV_VOLUME: {"model": {"$ref": f"{name}_model"}}}},
            {
                name: {
                    LV_MACHINE: {
                        "model": machine_model({"volume": {"$ref": f"{name}_model"}})
                    }
                }
            },
        ]
    session = Session.model_validate({"objects": objects})
    with session:
        a, b = session.all(LVMachine)
        with SnapshottableGroup(session.all(Snapshottable)).snapshot():
            a.power_off()
            b.power_off()
        assert a.is_powered_on and b.is_powered_on
