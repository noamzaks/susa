from __future__ import annotations

import functools
import inspect
import types
import typing
from collections.abc import Callable, Mapping
from typing import Annotated, Any, Literal, Union

import pydantic
from pydantic.json_schema import SkipJsonSchema
from typing_extensions import NotRequired, Self, TypedDict

from susa.communicator.rlogin import RloginCommunicator
from susa.communicator.serial import SerialCommunicator
from susa.communicator.ssh import SSHCommunicator
from susa.communicator.telnet import TelnetCommunicator
from susa.communicator.unix import UnixCommunicator
from susa.libvirt.disk_model import DiskModel
from susa.libvirt.interface_model import InterfaceModel
from susa.libvirt.machine import LVMachine
from susa.libvirt.machine_model import MachineModel, SnapshotModel
from susa.libvirt.network import LVNetwork
from susa.libvirt.network_model import NetworkModel
from susa.libvirt.volume import LVVolume
from susa.libvirt.volume_model import VolumeModel

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
        UnixCommunicator,
    )
}


# An object made elsewhere, `{"$ref": "name"}`, or an attribute of one, `{"$ref": "name.attribute"}`.
class Reference(pydantic.BaseModel, extra="forbid"):
    ref: str = pydantic.Field(alias="$ref")

    def resolve(self, objects: Mapping[str, Any]) -> Any:
        name, *attributes = self.ref.split(".")
        if name not in objects:
            raise ValueError(f"Unknown reference {self.ref!r}")
        return functools.reduce(getattr, attributes, objects[name])


# Public methods returning `Self`.
def builders(cls: type[Any]) -> dict[str, Callable[..., Any]]:
    return {
        name: method
        for name, method in inspect.getmembers(cls, inspect.isfunction)
        if not name.startswith("_")
        and typing.get_type_hints(method).get("return") is Self
    }


# A method's parameters, but `self`.
def parameters(method: Callable[..., Any]) -> list[inspect.Parameter]:
    _, *result = inspect.signature(method).parameters.values()
    return result


def needs_arguments(method: Callable[..., Any]) -> bool:
    return any(p.default is p.empty for p in parameters(method))


# A method's arguments by name, those it has defaults for optional.
@functools.cache
def arguments_type(method: Callable[..., Any]) -> Any:
    hints = typing.get_type_hints(method)
    fields = {}
    for p in parameters(method):
        field = argument_type(hints.get(p.name, Any))
        fields[p.name] = field if p.default is p.empty else NotRequired[field]
    return typed_dict(method.__qualname__.replace(".", "_"), fields)


# The parameter's type, or a reference or a recipe, where types only Python objects can be (e.g. a machine) aren't in
# the JSON schema.
def argument_type(annotation: Any) -> Any:
    members = (
        typing.get_args(annotation)
        if typing.get_origin(annotation) in (Union, types.UnionType)
        else (annotation,)
    )
    json = [m if has_json_schema(m) else SkipJsonSchema[m] for m in members]  # type: ignore
    return Union[(*json, Reference, "Recipe")]


def has_json_schema(annotation: Any) -> bool:
    try:
        pydantic.TypeAdapter(annotation).json_schema()
    except pydantic.PydanticUserError:
        return False
    return True


# `{method: arguments}`, with the arguments by name or else just the first.
def step_type(name: str, method: Callable[..., Any]) -> Any:
    arguments = arguments_type(method)
    names = {p.name for p in parameters(method)}
    first = next(iter(parameters(method)), None)

    def by_name(value: Any) -> Any:
        if first is None or isinstance(value, dict) and value.keys() <= names:
            return value
        return {first.name: value}

    hints = typing.get_type_hints(method)
    first_type = Any if first is None else argument_type(hints.get(first.name, Any))
    validator = pydantic.BeforeValidator(
        by_name,
        json_schema_input_type=Union[arguments, first_type],  # noqa: UP007
    )
    fields = {name: Annotated[arguments, validator]}
    return typed_dict(f"{arguments.__name__}_step", fields)


# Builder steps, each of which can be only the method's name if it needs no arguments.
def steps_type(cls: type[Any]) -> Any:
    methods = builders(cls)
    steps = [Annotated[step_type(n, m), pydantic.Tag(n)] for n, m in methods.items()]
    step: Any = Annotated[Union[tuple(steps)], pydantic.Discriminator(single_key)]  # noqa: UP007
    names = tuple(n for n, m in methods.items() if not needs_arguments(m))
    validator = pydantic.BeforeValidator(
        lambda value: {value: {}} if isinstance(value, str) else value,
        json_schema_input_type=Union[step, Literal[names]] if names else step,  # noqa: UP007
    )
    return list[Annotated[step, validator]]


# Each class' `{"<class name>": recipe}`, by its builder steps if it has builder methods, or else by its constructor's
# arguments.
def recipes_type(classes: Mapping[str, type[Any]]) -> Any:
    recipes = []
    for name, cls in classes.items():
        recipe = steps_type(cls) if builders(cls) else arguments_type(cls.__init__)
        recipe_type = typed_dict(f"{cls.__name__}Recipe", {name: recipe})
        recipes.append(Annotated[recipe_type, pydantic.Tag(name)])
    return Annotated[Union[tuple(recipes)], pydantic.Discriminator(single_key)]  # noqa: UP007


# Arguments that only Python objects can be (e.g. a machine) are given as references (or recipes).
def typed_dict(name: str, fields: dict[str, Any]) -> Any:
    config = pydantic.ConfigDict(extra="forbid", arbitrary_types_allowed=True)
    return pydantic.with_config(config)(TypedDict(name, fields))  # type: ignore


def single_key(value: Any) -> str | None:
    if isinstance(value, dict) and len(value) == 1:
        return str(next(iter(value)))
    return None


def recipe_kind(value: Any) -> str | None:
    cls = CLASSES.get(single_key(value) or "")
    if cls is None:
        return None
    return "builder" if builders(cls) else "constructor"


# The arguments, with references and recipes replaced by what they refer to and make.
def resolve(arguments: Mapping[str, Any], objects: Mapping[str, Any]) -> dict[str, Any]:
    return {name: resolve_value(value, objects) for name, value in arguments.items()}


def resolve_value(value: Any, objects: Mapping[str, Any]) -> Any:
    if isinstance(value, Reference):
        return value.resolve(objects)
    if isinstance(value, Recipe):
        return value.make(**objects)
    return value


# `{"<class name>": arguments}`, made by the constructor.
class ConstructorRecipe(pydantic.RootModel[dict[str, Any]]):
    root: recipes_type({n: c for n, c in CLASSES.items() if not builders(c)})  # type: ignore

    def make(self, objects: Mapping[str, Any]) -> Any:
        [(name, arguments)] = self.root.items()
        return CLASSES[name](**resolve(arguments, objects))


# `{"<class name>": steps}`, made by calling builder methods (public methods returning `Self`, e.g. the models').
class BuilderRecipe(pydantic.RootModel[dict[str, Any]]):
    root: recipes_type({n: c for n, c in CLASSES.items() if builders(c)})  # type: ignore

    def make(self, objects: Mapping[str, Any]) -> Any:
        [(name, steps)] = self.root.items()
        result = CLASSES[name]()
        for step in steps:
            [(method, arguments)] = step.items()
            getattr(result, method)(**resolve(arguments, objects))
        return result


# `{"<class name>": recipe}`, any argument of which can be a recipe itself, or a `Reference`.
class Recipe(pydantic.RootModel[ConstructorRecipe | BuilderRecipe]):
    root: Annotated[
        Annotated[ConstructorRecipe, pydantic.Tag("constructor")]
        | Annotated[BuilderRecipe, pydantic.Tag("builder")],
        pydantic.Discriminator(recipe_kind),
    ]

    def make(self, **objects: Any) -> Any:
        return self.root.make(objects)
