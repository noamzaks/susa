from __future__ import annotations

import functools
import inspect
import operator
import typing
from collections.abc import Callable, Mapping
from typing import Any, cast

import pydantic
from pydantic.experimental.arguments_schema import generate_arguments_schema
from pydantic.json_schema import GenerateJsonSchema, JsonSchemaValue
from pydantic_core import core_schema
from typing_extensions import Self, override

# A recipe makes an object of a class from JSON. A class with builder methods (public methods returning `Self`) is
# made by builder steps, e.g. `[{"arch": "x86_64"}, "default", {"memory": 1073741824}]`, where a step is
# `{method: arguments}`, with an object of arguments by name or else just the first argument, or only the method's
# name if it needs none. Any other class is made from its constructor's arguments by name, e.g. `{"username": "root"}`.
# Any argument can be a reference to an object made elsewhere (see `resolve`), which is how arguments that aren't
# JSON (e.g. a machine) are given.

REFERENCE = core_schema.typed_dict_schema(
    {"$ref": core_schema.typed_dict_field(core_schema.str_schema())},
    extra_behavior="forbid",
    ref="Reference",
)


# The recipe, with its references to `objects` replaced by them: `{"$ref": "name"}`, or an attribute of one,
# `{"$ref": "name.attribute"}`.
def resolve(recipe: Any, objects: Mapping[str, Any]) -> Any:
    match recipe:
        case {"$ref": str(reference)} if len(recipe) == 1:
            name, *attributes = reference.split(".")
            if name not in objects:
                raise ValueError(f"Unknown reference {reference!r}")
            return functools.reduce(getattr, attributes, objects[name])
        case dict():
            return {key: resolve(value, objects) for key, value in recipe.items()}
        case list():
            return [resolve(value, objects) for value in recipe]
    return recipe


def recipe_schema(cls: type[Any]) -> core_schema.CoreSchema:
    builders = {
        name: method
        for name, method in inspect.getmembers(cls, inspect.isfunction)
        if not name.startswith("_")
        and typing.get_type_hints(method).get("return") is Self
    }
    if not builders:
        return core_schema.call_schema(arguments_schema(cls.__init__), cls)

    step = core_schema.tagged_union_schema(
        {name: step_schema(name, method) for name, method in builders.items()},
        discriminator=single_key,
    )
    # There's no going back from the built object to its recipe, so it's serialized as it is.
    return core_schema.no_info_after_validator_function(
        lambda steps: functools.reduce(lambda result, s: s(result), steps, cls()),
        core_schema.list_schema(step),
        serialization=core_schema.simple_ser_schema("any"),
    )


# `{name: schema}`, validated into what `schema` validates.
def keyed_schema(name: str, schema: core_schema.CoreSchema) -> core_schema.CoreSchema:
    return core_schema.no_info_after_validator_function(
        operator.itemgetter(name),
        core_schema.typed_dict_schema(
            {name: core_schema.typed_dict_field(schema)}, extra_behavior="forbid"
        ),
    )


# The key of a single-key object, or a string.
def single_key(value: Any) -> str | None:
    if isinstance(value, dict) and len(value) == 1:
        [value] = value
    return value if isinstance(value, str) else None


# A step, validated into a call of the method on the object being built.
def step_schema(name: str, method: Callable[..., Any]) -> core_schema.CoreSchema:
    arguments = arguments_schema(method)
    call = functools.partial(operator.methodcaller, name)
    with_arguments = keyed_schema(
        name, core_schema.call_schema(first_or_by_name(arguments), call)
    )
    _, *parameters = inspect.signature(method).parameters.values()
    if any(p.default is p.empty and p.kind is not p.VAR_POSITIONAL for p in parameters):
        return with_arguments
    only_name = core_schema.no_info_after_validator_function(
        lambda _: call(), core_schema.literal_schema([name])
    )
    return core_schema.union_schema([with_arguments, only_name])


# Arguments by name, or else just the first one.
def first_or_by_name(
    arguments: core_schema.ArgumentsV3Schema,
) -> core_schema.CoreSchema:
    if not arguments["arguments_schema"]:
        return arguments
    first = arguments["arguments_schema"][0]
    schema = first["schema"]
    if first["mode"] == "var_args":
        schema = core_schema.list_schema(schema)
    return core_schema.no_info_before_validator_function(
        lambda value: value if isinstance(value, dict) else {first["name"]: value},
        arguments,
        json_schema_input_schema=core_schema.union_schema(
            [arguments, schema, REFERENCE]
        ),
    )


# A method's arguments (but `self`) by name, which may be of types that aren't JSON (e.g. a machine).
def arguments_schema(method: Callable[..., Any]) -> core_schema.ArgumentsV3Schema:
    schema = generate_arguments_schema(
        method,
        parameters_callback=lambda index, *_: "skip" if index == 0 else None,
        config=pydantic.ConfigDict(arbitrary_types_allowed=True),
    )
    return cast(core_schema.ArgumentsV3Schema, schema)


# Recipes' JSON schemas, where any argument can be a reference, and those of types that aren't JSON can only be one.
class RecipeJsonSchema(GenerateJsonSchema):
    @override
    def arguments_v3_schema(
        self, schema: core_schema.ArgumentsV3Schema
    ) -> JsonSchemaValue:
        result = super().arguments_v3_schema(schema)
        reference = self.generate_inner(REFERENCE)
        for name, value in result["properties"].items():
            if reference not in [value, *value.get("anyOf", [])]:
                result["properties"][name] = {"anyOf": [value, reference]}
        return result

    @override
    def handle_invalid_for_json_schema(
        self, schema: Any, error_info: str
    ) -> JsonSchemaValue:
        return self.generate_inner(REFERENCE)
