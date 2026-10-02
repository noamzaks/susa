from __future__ import annotations

import functools
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic_core import SchemaValidator, core_schema
from typing_extensions import TypeAlias

from susa.communicator.rlogin import RloginCommunicator
from susa.communicator.serial import SerialCommunicator
from susa.communicator.ssh import SSHCommunicator
from susa.communicator.telnet import TelnetCommunicator
from susa.libvirt.disk_model import DiskModel
from susa.libvirt.interface_model import InterfaceModel
from susa.libvirt.machine import LVMachine
from susa.libvirt.machine_model import MachineModel, SnapshotModel
from susa.libvirt.network import LVNetwork
from susa.libvirt.network_model import NetworkModel
from susa.libvirt.volume import LVVolume
from susa.libvirt.volume_model import VolumeModel
from susa.utilities.recipe import (
    RecipeJsonSchema,
    keyed_schema,
    recipe_schema,
    resolve,
    single_key,
)

# What recipes (see `susa.utilities.recipe`) can make, by full class name: a recipe of one is `{name: its recipe}`, e.g.
# `{"susa.communicator.ssh.SSHCommunicator": {"username": "root", "password": "a"}}`.
CLASSES: dict[str, type[Any]] = {
    f"{cls.__module__}.{cls.__qualname__}": cls
    for cls in (
        MachineModel,
        NetworkModel,
        DiskModel,
        InterfaceModel,
        SnapshotModel,
        VolumeModel,
        LVNetwork,
        LVVolume,
        LVMachine,
        SerialCommunicator,
        SSHCommunicator,
        TelnetCommunicator,
        RloginCommunicator,
    )
}


# A recipe of an object: `{"<class name>": its recipe}` (see `susa.utilities.recipe`).
Recipe: TypeAlias = Mapping[str, Any]


def load(recipe: Any) -> Any:
    return json.loads(recipe.read_text()) if isinstance(recipe, Path) else recipe


# The object a recipe (or a JSON file of one) makes, where references are to `objects`.
def make(recipe: Recipe | Path, **objects: Any) -> Any:
    return validator().validate_python(resolve(load(recipe), objects))


# The JSON schema of a recipe of an object, or of a session (see `susa.session.Session.parse`).
def schema() -> dict[str, Any]:
    recipe = classes_schema()
    session = core_schema.list_schema(
        core_schema.dict_schema(
            core_schema.str_schema(), recipe, min_length=1, max_length=1
        )
    )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "SUSA recipe",
        **RecipeJsonSchema().generate(core_schema.union_schema([recipe, session])),
    }


@functools.cache
def validator() -> SchemaValidator:
    return SchemaValidator(classes_schema())


def classes_schema() -> core_schema.CoreSchema:
    return core_schema.tagged_union_schema(
        {name: keyed_schema(name, recipe_schema(cls)) for name, cls in CLASSES.items()},
        discriminator=single_key,
    )
