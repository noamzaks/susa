from __future__ import annotations

from typing import Any

import pytest
from typing_extensions import override

from susa.core.machine import Snapshottable, SnapshottableGroup
from susa.core.resource import Resource
from susa.core.session import Session
from susa.libvirt import Connection, LVMachine, LVNetwork, LVVolume, MachineModel
from susa.recipes import Recipe
from susa.utilities.generic import GIGA

MACHINE = "susa.libvirt.machine_model.MachineModel"
NETWORK = "susa.libvirt.network_model.NetworkModel"
VOLUME = "susa.libvirt.volume_model.VolumeModel"


# The models (which refer to each other, e.g. to reserve the machine's IP), then a machine on a network with an available
# IP, a volume of its own, and something named after its IP.
SESSION: list[dict[str, Any]] = [
    {"network_model": {NETWORK: ["default", "ip"]}},
    {"volume_model": {VOLUME: [{"pool": "default-pool"}, {"capacity": GIGA}]}},
    {
        "machine_model": {
            MACHINE: [
                {"arch": "x86_64"},
                "default",
                {"memory": GIGA},
                {"volume": {"$ref": "volume_model"}},
                {"network": {"$ref": "network_model"}},
            ]
        }
    },
    {
        "network": {
            "susa.libvirt.network.LVNetwork": {"model": {"$ref": "network_model"}}
        }
    },
    {"volume": {"susa.libvirt.volume.LVVolume": {"model": {"$ref": "volume_model"}}}},
    {
        "machine": {
            "susa.libvirt.machine.LVMachine": {"model": {"$ref": "machine_model"}}
        }
    },
    {"named": {MACHINE: [{"name": {"$ref": "machine.ip"}}]}},
]


def test_parse() -> None:
    session = Session.parse(SESSION)
    assert all(isinstance(o, Recipe) for o in session.objects.values())

    # Made and created in order (so the last refers to the machine's IP, known once its network exists), and destroyed
    # in reverse.
    with Connection("test:///default"), session:
        network = session.get("network", LVNetwork)
        machine = session.get("machine", LVMachine)
        assert session.get("volume", LVVolume).value is not None
        assert machine.is_powered_on
        [interface] = machine.model.get_interfaces() or []
        assert interface.source is not None
        assert interface.source.network == network.name
        assert session.get("named", MachineModel).get_name() == machine.ip
        with pytest.raises(TypeError):
            session.get("volume", LVMachine)
    assert machine.value is None


def test_parse_twice() -> None:
    with pytest.raises(ValueError):
        Session.parse([{"a": {MACHINE: []}}, {"a": {MACHINE: []}}])


class Failing(Resource):
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.alive = False

    @override
    def create(self) -> None:
        if self.fail:
            raise RuntimeError
        self.alive = True

    @override
    def destroy(self) -> None:
        self.alive = False


def test_session_create_fails() -> None:
    session = Session(a=Failing(), b=Failing(fail=True))
    with pytest.raises(RuntimeError):
        session.create()
    assert not session.get("a", Failing).alive


# A snapshot of each of a session's machines.
def test_session_snapshot() -> None:
    with Connection("test:///default"):
        a, b = (
            LVMachine(MachineModel().arch("x86_64").default().memory(GIGA))
            for _ in range(2)
        )
        with Session(a=a, b=b) as session:
            with SnapshottableGroup(session.all(Snapshottable)).snapshot():
                a.power_off()
                b.power_off()
            assert a.is_powered_on and b.is_powered_on
