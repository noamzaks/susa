from __future__ import annotations

import functools
import inspect
import typing
from abc import abstractmethod
from collections.abc import Callable, Mapping
from typing import Annotated, Any, ClassVar, Literal, Union

import pydantic
from pydantic.json_schema import GenerateJsonSchema, JsonSchemaValue
from typing_extensions import Self, override

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

# Arguments that aren't JSON (e.g. a machine) are given as references (or recipes).
CONFIG = pydantic.ConfigDict(extra="forbid", arbitrary_types_allowed=True)


# An object made elsewhere, `{"$ref": "name"}`, or an attribute of one, `{"$ref": "name.attribute"}`.
class Reference(pydantic.BaseModel):
    model_config = CONFIG

    ref: str = pydantic.Field(alias="$ref")

    def resolve(self, objects: Mapping[str, Any]) -> Any:
        name, *attributes = self.ref.split(".")
        if name not in objects:
            raise ValueError(f"Unknown reference {self.ref!r}")
        return functools.reduce(getattr, attributes, objects[name])


# A method's arguments by name, each of which can also be a reference or a recipe.
class Arguments(pydantic.BaseModel):
    model_config = CONFIG

    # With references and recipes replaced by what they refer to and make.
    def resolve(self, objects: Mapping[str, Any]) -> dict[str, Any]:
        resolved = {name: resolve(value, objects) for name, value in self}
        return dict(self.model_validate(resolved))


# `{method: arguments}`, calling a builder method.
class Step(pydantic.BaseModel):
    model_config = CONFIG

    def apply(self, result: Any, objects: Mapping[str, Any]) -> None:
        [(name, arguments)] = self
        getattr(result, name)(**arguments.resolve(objects))


# `{"<class name>": recipe}`.
class ClassRecipe(pydantic.BaseModel):
    model_config = CONFIG

    cls: ClassVar[type[Any]]

    @abstractmethod
    def make(self, objects: Mapping[str, Any]) -> Any: ...


# By the constructor's arguments.
class ConstructorRecipe(ClassRecipe):
    arguments: Arguments

    @override
    def make(self, objects: Mapping[str, Any]) -> Any:
        return self.cls(**self.arguments.resolve(objects))


# By builder steps, for a class with builder methods (public methods returning `Self`, e.g. the models).
class BuilderRecipe(ClassRecipe):
    steps: list[Step]

    @override
    def make(self, objects: Mapping[str, Any]) -> Any:
        result = self.cls()
        for step in self.steps:
            step.apply(result, objects)
        return result


def resolve(value: Any, objects: Mapping[str, Any]) -> Any:
    if isinstance(value, Reference):
        return value.resolve(objects)
    if isinstance(value, Recipe):
        return value.make(**objects)
    return value


def builders(cls: type[Any]) -> dict[str, Callable[..., Any]]:
    return {
        name: method
        for name, method in inspect.getmembers(cls, inspect.isfunction)
        if not name.startswith("_")
        and typing.get_type_hints(method).get("return") is Self
    }


@functools.cache
def arguments_model(method: Callable[..., Any]) -> type[Arguments]:
    hints = typing.get_type_hints(method)
    _, *parameters = inspect.signature(method).parameters.values()
    fields: dict[str, Any] = {
        p.name: (
            Union[hints.get(p.name, Any), Reference, "Recipe"],
            ... if p.default is p.empty else p.default,
        )
        for p in parameters
    }
    name = method.__qualname__.replace(".", "_")
    return pydantic.create_model(
        name, __base__=Arguments, __module__=__name__, **fields
    )


# `{name: arguments}`, with the arguments by name or else just the first.
def step_model(name: str, method: Callable[..., Any]) -> type[Step]:
    arguments = arguments_model(method)
    names = arguments.model_fields.keys()
    first = next(iter(names), None)

    def by_name(value: Any) -> Any:
        if first is None or isinstance(value, dict) and value.keys() <= names:
            return value
        return {first: value}

    first_type = Any if first is None else arguments.model_fields[first].annotation
    validator = pydantic.BeforeValidator(
        by_name,
        json_schema_input_type=Union[arguments, first_type],  # noqa: UP007
    )
    fields: dict[str, Any] = {name: (Annotated[arguments, validator], ...)}
    return pydantic.create_model(
        f"{arguments.__name__}_step", __base__=Step, __module__=__name__, **fields
    )


# Steps, each of which can be only the method's name if it needs no arguments.
def steps_type(cls: type[Any]) -> Any:
    methods = builders(cls)
    steps = [Annotated[step_model(n, m), pydantic.Tag(n)] for n, m in methods.items()]
    step: Any = Annotated[Union[tuple(steps)], pydantic.Discriminator(single_key)]  # noqa: UP007
    names = tuple(n for n, m in methods.items() if not needs_arguments(m))
    validator = pydantic.BeforeValidator(
        lambda value: {value: {}} if isinstance(value, str) else value,
        json_schema_input_type=Union[step, Literal[names]] if names else step,  # noqa: UP007
    )
    return list[Annotated[step, validator]]


def needs_arguments(method: Callable[..., Any]) -> bool:
    fields = arguments_model(method).model_fields.values()
    return any(field.is_required() for field in fields)


def class_recipe_model(name: str, cls: type[Any]) -> type[ClassRecipe]:
    fields: dict[str, Any]
    if builders(cls):
        base: type[ClassRecipe] = BuilderRecipe
        fields = {"steps": (steps_type(cls), pydantic.Field(alias=name))}
    else:
        base = ConstructorRecipe
        arguments = arguments_model(cls.__init__)
        fields = {"arguments": (arguments, pydantic.Field(alias=name))}
    model = pydantic.create_model(
        f"{cls.__name__}Recipe", __base__=base, __module__=__name__, **fields
    )
    model.cls = cls
    return model


def single_key(value: Any) -> str | None:
    if isinstance(value, dict) and len(value) == 1:
        return str(next(iter(value)))
    return None


RECIPES = [
    Annotated[class_recipe_model(name, cls), pydantic.Tag(name)]
    for name, cls in CLASSES.items()
]


# `{"<class name>": recipe}` (see `ClassRecipe`), any argument of which can be a recipe itself, or a `Reference`.
class Recipe(pydantic.RootModel[ClassRecipe]):
    root: Annotated[Union[tuple(RECIPES)], pydantic.Discriminator(single_key)]  # type: ignore # noqa: UP007

    def make(self, **objects: Any) -> Any:
        return self.root.make(objects)


# Arguments that aren't JSON (e.g. a machine) can only be references or recipes.
class RecipeJsonSchema(GenerateJsonSchema):
    @override
    def handle_invalid_for_json_schema(
        self, schema: Any, error_info: str
    ) -> JsonSchemaValue:
        return {"not": {}}
