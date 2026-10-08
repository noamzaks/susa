from __future__ import annotations

from typing import Any

import libvirt as lv
import pydantic
import pytest

from susa.core.machine import Snapshottable, SnapshottableGroup
from susa.libvirt import Connection, LVMachine, LVNetwork, LVVolume, MachineModel
from susa.recipes.session import Session
from susa.utilities.generic import GIGA

MACHINE = "susa.libvirt.machine_model.MachineModel"
NETWORK = "susa.libvirt.network_model.NetworkModel"
VOLUME = "susa.libvirt.volume_model.VolumeModel"
LV_NETWORK = "susa.libvirt.network.LVNetwork"
LV_VOLUME = "susa.libvirt.volume.LVVolume"
LV_MACHINE = "susa.libvirt.machine.LVMachine"


def machine_model(*steps: Any) -> dict[str, Any]:
    return {MACHINE: [{"arch": "x86_64"}, "default", {"memory": GIGA}, *steps]}


SESSION: list[dict[str, Any]] = [
    {"network_model": {NETWORK: ["default", "ip"]}},
    {"volume_model": {VOLUME: [{"pool": "default-pool"}, {"capacity": GIGA}]}},
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


def test_session() -> None:
    session = Session.model_validate({"objects": SESSION})
    with Connection("test:///default"), session:
        network = session.get("network", LVNetwork)
        machine = session.get("machine", LVMachine)
        assert session.get("volume", LVVolume).value is not None
        assert machine.is_powered_on
        [interface] = machine.model.get_interfaces() or []
        assert interface.source is not None
        assert interface.source.network == network.name
        # Made once the machine's created.
        assert session.get("named", MachineModel).get_name() == machine.ip
        with pytest.raises(AssertionError):
            session.get("volume", LVMachine)
    assert machine.value is None


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
    with Connection("test:///default"), pytest.raises(ValueError):
        session.create()


def test_session_create_fails() -> None:
    network = {LV_NETWORK: {"model": {NETWORK: ["default", "ip"]}}}
    volume = {LV_VOLUME: {"model": {VOLUME: [{"pool": "nothing"}]}}}
    session = Session.model_validate(
        {"objects": [{"network": network}, {"volume": volume}]}
    )
    with Connection("test:///default"):
        with pytest.raises(lv.libvirtError):
            session.create()
        assert session.get("network", LVNetwork).value is None


def test_session_snapshot() -> None:
    machine = {LV_MACHINE: {"model": machine_model()}}
    session = Session.model_validate({"objects": [{"a": machine}, {"b": machine}]})
    with Connection("test:///default"), session:
        a, b = session.all(LVMachine)
        with SnapshottableGroup(session.all(Snapshottable)).snapshot():
            a.power_off()
            b.power_off()
        assert a.is_powered_on and b.is_powered_on
