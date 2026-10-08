from __future__ import annotations

import functools
import importlib
import importlib.util
import inspect
import types
import typing
from collections.abc import Callable, Mapping
from typing import Annotated, Any, Literal, Union

import pydantic
from pydantic.json_schema import SkipJsonSchema
from typing_extensions import NotRequired, Self, TypedDict

PACKAGES = {
    "susa.communicator": [
        "susa.communicator.serial.SerialCommunicator",
        "susa.communicator.ssh.SSHCommunicator",
        "susa.communicator.telnet.TelnetCommunicator",
        "susa.communicator.rlogin.RloginCommunicator",
        "susa.communicator.unix.UnixCommunicator",
    ],
    "susa.libvirt": [
        "susa.libvirt.machine_model.MachineModel",
        "susa.libvirt.network_model.NetworkModel",
        "susa.libvirt.disk_model.DiskModel",
        "susa.libvirt.interface_model.InterfaceModel",
        "susa.libvirt.machine_model.SnapshotModel",
        "susa.libvirt.volume_model.VolumeModel",
        "susa.libvirt.network.LVNetwork",
        "susa.libvirt.volume.LVVolume",
        "susa.libvirt.machine.LVMachine",
    ],
}


def import_class(name: str) -> type[Any]:
    module, _, cls = name.rpartition(".")
    result: type[Any] = getattr(importlib.import_module(module), cls)
    return result


def installed_classes() -> dict[str, type[Any]]:
    result: dict[str, type[Any]] = {}
    for package, names in PACKAGES.items():
        if importlib.util.find_spec(package) is None:
            continue
        result |= {name: import_class(name) for name in names}
    return result


CLASSES = installed_classes()


class Reference(pydantic.BaseModel, extra="forbid"):
    ref: str = pydantic.Field(alias="$ref")

    def resolve(self, objects: Mapping[str, Any]) -> Any:
        name, *attributes = self.ref.split(".")
        if name not in objects:
            raise ValueError(f"Unknown reference {self.ref!r}")
        return functools.reduce(getattr, attributes, objects[name])


def builders(cls: type[Any]) -> dict[str, Callable[..., Any]]:
    return {
        name: method
        for name, method in inspect.getmembers(cls, inspect.isfunction)
        if not name.startswith("_")
        and typing.get_type_hints(method).get("return") is Self
    }


def parameters(method: Callable[..., Any]) -> list[inspect.Parameter]:
    _, *result = inspect.signature(method).parameters.values()
    return result


def needs_arguments(method: Callable[..., Any]) -> bool:
    return any(p.default is p.empty for p in parameters(method))


@functools.cache
def arguments_type(method: Callable[..., Any]) -> Any:
    hints = typing.get_type_hints(method)
    fields = {}
    for p in parameters(method):
        field = argument_type(hints.get(p.name, Any))
        fields[p.name] = field if p.default is p.empty else NotRequired[field]
    return typed_dict(method.__qualname__.replace(".", "_"), fields)


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


def recipes_type(classes: Mapping[str, type[Any]]) -> Any:
    # Never picked by `recipe_kind`.
    if not classes:
        return dict[str, Any]
    recipes = []
    for name, cls in classes.items():
        recipe = steps_type(cls) if builders(cls) else arguments_type(cls.__init__)
        recipe_type = typed_dict(f"{cls.__name__}Recipe", {name: recipe})
        recipes.append(Annotated[recipe_type, pydantic.Tag(name)])
    return Annotated[Union[tuple(recipes)], pydantic.Discriminator(single_key)]  # noqa: UP007


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


def resolve(arguments: Mapping[str, Any], objects: Mapping[str, Any]) -> dict[str, Any]:
    return {name: resolve_value(value, objects) for name, value in arguments.items()}


def resolve_value(value: Any, objects: Mapping[str, Any]) -> Any:
    if isinstance(value, Reference):
        return value.resolve(objects)
    if isinstance(value, Recipe):
        return value.make(**objects)
    return value


class ConstructorRecipe(pydantic.RootModel[dict[str, Any]]):
    root: recipes_type({n: c for n, c in CLASSES.items() if not builders(c)})  # type: ignore

    def make(self, objects: Mapping[str, Any]) -> Any:
        [(name, arguments)] = self.root.items()
        return CLASSES[name](**resolve(arguments, objects))


class BuilderRecipe(pydantic.RootModel[dict[str, Any]]):
    root: recipes_type({n: c for n, c in CLASSES.items() if builders(c)})  # type: ignore

    def make(self, objects: Mapping[str, Any]) -> Any:
        [(name, steps)] = self.root.items()
        result = CLASSES[name]()
        for step in steps:
            [(method, arguments)] = step.items()
            getattr(result, method)(**resolve(arguments, objects))
        return result


class Recipe(pydantic.RootModel[ConstructorRecipe | BuilderRecipe]):
    root: Annotated[
        Annotated[ConstructorRecipe, pydantic.Tag("constructor")]
        | Annotated[BuilderRecipe, pydantic.Tag("builder")],
        pydantic.Discriminator(recipe_kind),
    ]

    def make(self, **objects: Any) -> Any:
        return self.root.make(objects)
