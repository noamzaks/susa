from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pydantic
import pytest
from typing_extensions import override

from susa.communicator.serial import SerialCommunicator
from susa.communicator.shell import Login
from susa.communicator.ssh import SSHCommunicator
from susa.core.machine import Serial, SerialAccessible
from susa.core.resource import Resource
from susa.libvirt import Connection, LVMachine, LVNetwork, LVVolume, MachineModel
from susa.recipes import CLASSES, make, schema
from susa.session import Session

MACHINE = "susa.libvirt.machine_model.MachineModel"
SSH = "susa.communicator.ssh.SSHCommunicator"
SERIAL = "susa.communicator.serial.SerialCommunicator"


def test_make_builder_steps() -> None:
    recipe = {MACHINE: [{"name": "test"}, {"arch": "mips"}, "default"]}
    assert make(recipe) == MachineModel("test").arch("mips").default()


class Serials(SerialAccessible):
    @override
    def serial(self) -> Serial:
        raise NotImplementedError


def test_make_references() -> None:
    machine = Serials()
    recipe = {SERIAL: {"machine": {"$ref": "machine"}, "login": {"password": "a"}}}
    serial: SerialCommunicator = make(recipe, machine=machine)
    assert (serial.machine, serial.prelude) == (machine, Login("a"))

    # A reference to an attribute.
    recipe = {SERIAL: {"machine": {"$ref": "serial.machine"}}}
    assert make(recipe, serial=serial).machine is machine


@pytest.mark.parametrize(
    "recipe",
    (
        {"susa.nothing.Nothing": {}},
        {SSH: {"username": "root"}},
        {SSH: {"machine": "h", "username": "root", "colour": "red"}},
        {MACHINE: ["unknown"]},
        {MACHINE: [], SSH: {}},
        {SSH: {"machine": {"$ref": "nothing"}, "username": "root"}},
    ),
)
def test_make_invalid(recipe: dict[str, Any]) -> None:
    with pytest.raises((pydantic.ValidationError, ValueError)):
        make(recipe)


def test_make_file(tmp_path: Path) -> None:
    path = tmp_path / "machine.json"
    path.write_text(json.dumps({MACHINE: [{"name": "test"}, {"arch": "mips"}]}))
    assert make(path) == MachineModel("test").arch("mips")


# A machine on a network with an available IP, a volume of its own, and a shell on it.
SESSION: list[dict[str, Any]] = [
    {"network": {"susa.libvirt.network.LVNetwork": {"model": ["default", "ip"]}}},
    {
        "volume": {
            "susa.libvirt.volume.LVVolume": {
                "model": [{"capacity": 1 << 30}],
                "pool": "default-pool",
            }
        }
    },
    {
        "machine": {
            "susa.libvirt.machine.LVMachine": {
                "model": [
                    {"arch": "x86_64"},
                    "default",
                    {"memory": 1 << 30},
                    {
                        "volume": {
                            "volume": {"$ref": "volume.model"},
                            "pool": "default-pool",
                        }
                    },
                    {"network": {"$ref": "network.model"}},
                ]
            }
        }
    },
    {"ssh": {SSH: {"machine": {"$ref": "machine"}, "username": "root"}}},
]


def test_parse() -> None:
    with Connection("test:///default"):
        session = Session.parse(SESSION)
        network = session.get("network", LVNetwork)
        machine = session.get("machine", LVMachine)
        assert session.get("ssh", SSHCommunicator).machine is machine
        [interface] = machine.model.get_interfaces()
        assert interface.get_network() == network.name
        with pytest.raises(TypeError):
            session.get("volume", LVMachine)

    # Created in order (but the communicator, as there's no server), and destroyed in reverse.
    with Connection("test:///default"), Session.parse(SESSION[:-1]) as session:
        machine = session.get("machine", LVMachine)
        assert session.get("volume", LVVolume).value is not None
        assert machine.is_powered_on
        assert (
            machine.ip in session.get("network", LVNetwork).model.get_hosts().values()
        )
    assert machine.value is None


def test_parse_twice() -> None:
    with pytest.raises(ValueError):
        Session.parse([{"a": {MACHINE: []}}, {"a": {MACHINE: []}}])


def test_schema() -> None:
    root = schema()
    single, many = root["anyOf"]
    recipes = {
        name: s["properties"][name] for s in single["oneOf"] for name in s["properties"]
    }
    assert set(recipes) == set(CLASSES)
    assert many["type"] == "array"
    ssh = recipes[SSH]
    assert ssh["required"] == ["machine", "username"]
    # Arguments that aren't JSON (a machine) can only be references, and any other can be one.
    reference = {"$ref": "#/$defs/Reference"}
    assert reference in ssh["properties"]["machine"]["anyOf"]
    assert reference in ssh["properties"]["port"]["anyOf"]
    assert root["$defs"]["Reference"]["required"] == ["$ref"]


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
