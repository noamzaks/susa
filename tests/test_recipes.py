from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pydantic
import pytest

from susa.libvirt import (
    LVDiskModel,
    LVInterfaceModel,
    LVMachine,
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
LV_MACHINE = "susa.libvirt.machine.LVMachine"
SUBNET = "susa.utilities.networking.SubnetReservation"


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


def test_make_references() -> None:
    model = LVMachineModel("test")
    recipe = {LV_MACHINE: {"model": {"$ref": "model"}}}
    machine: LVMachine = Recipe.model_validate(recipe).make(model=model)
    assert machine.model is model

    recipe = {LV_MACHINE: {"model": {"$ref": "machine.model"}}}
    assert Recipe.model_validate(recipe).make(machine=machine).model is model


@pytest.mark.parametrize(
    "recipe",
    (
        {"susa.nothing.Nothing": {}},
        {LV_MACHINE: {}},
        {SUBNET: {"subnets": "10.0.0.0/8", "colour": "red"}},
        {MACHINE: ["unknown"]},
        {MACHINE: [], SUBNET: {}},
        {SUBNET: {"host": {"$ref": "nothing"}}},
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
    assert defs["LVMachine___init__"]["required"] == ["model"]
    subnet = defs["SubnetReservation___init__"]
    for argument in ("host", "lock", "subnets"):
        assert {"$ref": "#/$defs/Reference"} in subnet["properties"][argument]["anyOf"]
