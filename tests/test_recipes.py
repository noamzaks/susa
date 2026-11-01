from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pydantic
import pytest
from typing_extensions import override

from susa.communicators.login import Login
from susa.communicators.serial import SerialCommunicator
from susa.core.machine import Serial, SerialAccessible
from susa.libvirt import (
    LVDiskModel,
    LVInterfaceModel,
    LVMachineModel,
    LVNetworkModel,
)
from susa.recipes import CLASSES, Recipe
from susa.utilities.generic import GIGA

MACHINE = "susa.libvirt.machine_model.LVMachineModel"
NETWORK = "susa.libvirt.network_model.LVNetworkModel"
DISK = "susa.libvirt.disk_model.LVDiskModel"
INTERFACE = "susa.libvirt.interface_model.LVInterfaceModel"
VOLUME = "susa.libvirt.volume_model.LVVolumeModel"
MAC = "52:54:00:12:34:56"
SSH = "susa.communicators.ssh.SSHCommunicator"
SERIAL = "susa.communicators.serial.SerialCommunicator"


def make_recipe(recipe: dict[str, Any]) -> Any:
    return Recipe.model_validate(recipe).make()


def test_make_builder_steps() -> None:
    recipe = {MACHINE: [{"name": "test"}, {"arch": "mips"}, "default"]}
    assert make_recipe(recipe) == LVMachineModel("test").arch("mips").default()


def test_make_models() -> None:
    disk = {DISK: [{"source": "somewhere"}]}
    interface = {INTERFACE: [{"mac": MAC}, {"network": "test"}]}
    machine = make_recipe(
        {
            MACHINE: [
                {"name": "test"},
                {"arch": "x86_64"},
                "default",
                {"memory": 4 * GIGA},
                {"cpu": "2"},
                {"efi": {"secure_boot": True}},
                {"kernel": {"kernel": "vmlinux", "cmdline": "console=ttyS0"}},
                {"disk": disk},
                {"interface": {"interface": interface}},
                {"qemu_args": ["-cpu", "max"]},
            ]
        }
    )
    expected = (
        LVMachineModel("test")
        .arch("x86_64")
        .default()
        .memory(4 * GIGA)
        .cpu(2)
        .efi(secure_boot=True)
        .kernel("vmlinux", cmdline="console=ttyS0")
        .disk(LVDiskModel().source("somewhere"))
        .interface(LVInterfaceModel(mac=MAC).network("test"))
        .qemu_args(["-cpu", "max"])
    )
    assert machine == expected

    network = make_recipe(
        {
            NETWORK: [
                {"name": "test"},
                "default",
                {"ip": {"address": "10.0.0.1", "netmask": "255.255.0.0"}},
                {
                    "interface": {
                        "interface": {INTERFACE: [{"mac": MAC}]},
                        "ip": "10.0.0.10",
                    }
                },
                "nat",
            ]
        }
    )
    expected_network = (
        LVNetworkModel("test")
        .default()
        .ip("10.0.0.1", "255.255.0.0")
        .interface(LVInterfaceModel(mac=MAC), "10.0.0.10")
        .nat()
    )
    assert network == expected_network


@pytest.mark.parametrize(
    "steps",
    (
        ["unknown"],
        ["arch"],
        [{"arch": "x86_64", "cpu": 2}],
        [{"efi": {"loader": "loader"}}],
        [{"efi": {"secure_boot": "maybe"}}],
        [{"memory": "a lot"}],
        [{"qemu_args": "-cpu"}],
    ),
)
def test_make_invalid_steps(steps: list[Any]) -> None:
    with pytest.raises((pydantic.ValidationError, ValueError)):
        Recipe.model_validate({MACHINE: [{"arch": "x86_64"}, *steps]}).make()


class Serials(SerialAccessible):
    @override
    def serial(self) -> Serial:
        raise NotImplementedError


def test_make_references() -> None:
    machine = Serials()
    recipe = {SERIAL: {"machine": {"$ref": "machine"}, "login": {"password": "a"}}}
    serial: SerialCommunicator = Recipe.model_validate(recipe).make(machine=machine)
    assert (serial.machine, serial.prelude) == (machine, Login("a"))

    recipe = {SERIAL: {"machine": {"$ref": "serial.machine"}}}
    assert Recipe.model_validate(recipe).make(serial=serial).machine is machine


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
        Recipe.model_validate(recipe).make()


def test_make_file(tmp_path: Path) -> None:
    path = tmp_path / "machine.json"
    path.write_text(json.dumps({MACHINE: [{"name": "test"}, {"arch": "mips"}]}))
    recipe = Recipe.model_validate_json(path.read_text())
    assert recipe.make() == LVMachineModel("test").arch("mips")


def test_schema() -> None:
    schema = Recipe.model_json_schema()
    defs = schema["$defs"]
    for name, cls in CLASSES.items():
        assert list(defs[f"{cls.__name__}Recipe"]["properties"]) == [name]
    ssh = defs["SSHCommunicator___init__"]
    assert ssh["required"] == ["ip", "username"]
    for argument in ("ip", "port", "host"):
        assert {"$ref": "#/$defs/Reference"} in ssh["properties"][argument]["anyOf"]
