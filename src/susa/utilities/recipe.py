from __future__ import annotations

import inspect
import typing
from collections.abc import Callable, Iterator
from typing import Any, TypeVar

from pydantic.experimental.arguments_schema import generate_arguments_schema
from pydantic_core import core_schema
from typing_extensions import Self, TypeAlias

T = TypeVar("T")

Method: TypeAlias = Callable[..., Any]
Step: TypeAlias = Callable[[Any], object]
Arguments: TypeAlias = tuple[tuple[Any, ...], dict[str, Any]]

# A recipe builds an object by calling its builder methods (public methods returning `Self`) in order, e.g.
# `[{"arch": "x86_64"}, "default", {"efi": {"loader": ..., "nvram": ...}}]`. A step is `{method: arguments}`, with
# an object of arguments by name or else just the first argument, or only the method's name if it needs none.


def recipe_schema(cls: type[T]) -> core_schema.CoreSchema:
    def cook(steps: list[Step]) -> T:
        result = cls()
        for step in steps:
            step(result)
        return result

    step = core_schema.tagged_union_schema(
        {name: step_schema(name, method) for name, method in builder_methods(cls)},
        discriminator=step_name,
    )
    # There's no going back from the cooked object to its recipe, so it's serialized as it is.
    return core_schema.no_info_after_validator_function(
        cook,
        core_schema.list_schema(step),
        serialization=core_schema.simple_ser_schema("any"),
    )


def builder_methods(cls: type[Any]) -> Iterator[tuple[str, Method]]:
    for name, method in inspect.getmembers(cls, inspect.isfunction):
        if (
            not name.startswith("_")
            and typing.get_type_hints(method).get("return") is Self
        ):
            yield name, method


def step_name(step: Any) -> str | None:
    if isinstance(step, dict) and len(step) == 1:
        step = next(iter(step))
    return step if isinstance(step, str) else None


def step_schema(name: str, method: Method) -> core_schema.CoreSchema:
    with_arguments = core_schema.no_info_after_validator_function(
        lambda step: bind(method, step[name]),
        core_schema.typed_dict_schema(
            {name: core_schema.typed_dict_field(arguments_schema(method))},
            extra_behavior="forbid",
        ),
    )
    if needs_arguments(method):
        return with_arguments
    only_name = core_schema.no_info_after_validator_function(
        lambda _: bind(method, ((), {})), core_schema.literal_schema([name])
    )
    return core_schema.union_schema([with_arguments, only_name])


def arguments_schema(method: Method) -> core_schema.CoreSchema:
    by_name = generate_arguments_schema(
        method, parameters_callback=lambda index, *_: "skip" if index == 0 else None
    )
    if not by_name["arguments_schema"]:
        return by_name
    first = by_name["arguments_schema"][0]
    first_schema = first["schema"]
    if first["mode"] == "var_args":
        first_schema = core_schema.list_schema(first_schema)
    only_first = core_schema.no_info_before_validator_function(
        lambda value: {first["name"]: value},
        by_name,
        json_schema_input_schema=first_schema,
    )
    return core_schema.tagged_union_schema(
        {"by_name": by_name, "first": only_first},
        discriminator=lambda value: "by_name" if isinstance(value, dict) else "first",
    )


def needs_arguments(method: Method) -> bool:
    return any(
        p.default is p.empty and p.kind is not p.VAR_POSITIONAL
        for p in list(inspect.signature(method).parameters.values())[1:]
    )


def bind(method: Method, arguments: Arguments) -> Step:
    args, kwargs = arguments
    return lambda obj: method(obj, *args, **kwargs)
