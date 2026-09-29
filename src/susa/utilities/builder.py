from __future__ import annotations

import functools
import inspect
import operator
import typing
from collections.abc import Callable
from typing import Annotated, Any, Literal, TypeVar

import pydantic
from typing_extensions import Self, TypeAlias

T = TypeVar("T")

Call: TypeAlias = Callable[[Any], object]

FORBID_EXTRA = pydantic.ConfigDict(extra="forbid")


# The pydantic type of JSON "builder calls", which build a `cls()` by calling its builder methods (public methods
# returning `Self`) in order, e.g. `[{"arch": "x86_64"}, "default", {"efi": {"loader": ..., "nvram": ...}}]`. A
# string calls a method without arguments, and `{method: value}` passes an object's items as keyword arguments,
# and anything else as the first argument (a list for `*args`).
@functools.cache
def builder_calls(cls: type[T]) -> Any:
    methods = [
        BuilderMethod(cls, name, function)
        for name, function in inspect.getmembers(cls, inspect.isfunction)
        if not name.startswith("_")
        and typing.get_type_hints(function).get("return") is Self
    ]
    call: Any = Annotated[
        functools.reduce(operator.or_, (m.type for m in methods)),
        pydantic.Discriminator(method_name),
    ]

    def build(calls: list[Call]) -> T:
        result = cls()
        for c in calls:
            c(result)
        return result

    return Annotated[list[call], pydantic.AfterValidator(build)]


def method_name(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and len(value) == 1:
        return str(next(iter(value)))
    return None


class BuilderMethod:
    def __init__(self, owner: type[Any], name: str, function: Call) -> None:
        self.owner = owner
        self.name = name
        self.function = function
        self.parameters = list(inspect.signature(function).parameters.values())[1:]
        hints = typing.get_type_hints(function)
        self.fields: dict[str, Any] = {}
        for p in self.parameters:
            # Sanity.
            assert p.kind is not p.VAR_KEYWORD
            if p.kind is p.VAR_POSITIONAL:
                self.fields[p.name] = (list[hints[p.name]], [])  # type: ignore
            else:
                default = ... if p.default is p.empty else p.default
                self.fields[p.name] = (hints[p.name], default)
        self.optional = [default is not ... for _, default in self.fields.values()]
        self.arguments = pydantic.create_model(
            f"{owner.__name__}_{name}_arguments", __config__=FORBID_EXTRA, **self.fields
        )
        self.type = Annotated[self.call_type(), pydantic.Tag(name)]

    # A call is `{name: value}`, or just `name` if every parameter is optional.
    def call_type(self) -> Any:
        call: Any = Annotated[
            pydantic.create_model(
                f"{self.owner.__name__}_{self.name}",
                __config__=FORBID_EXTRA,
                **{self.name: (self.value_type(), ...)},  # type: ignore
            ),
            pydantic.AfterValidator(lambda c: self.call(getattr(c, self.name))),
        ]
        if all(self.optional):
            call |= Annotated[
                Literal[self.name],
                pydantic.AfterValidator(lambda _: self.call(self.arguments())),
            ]
        return call

    # The value is an object of keyword arguments, or the first argument if the rest are optional.
    def value_type(self) -> Any:
        if not self.optional or not all(self.optional[1:]):
            return self.arguments
        first, (annotation, _) = next(iter(self.fields.items()))
        return Annotated[
            Annotated[self.arguments, pydantic.Tag("keywords")]
            | Annotated[annotation, pydantic.Tag("first")],
            pydantic.Discriminator(
                lambda v: "keywords" if isinstance(v, dict) else "first"
            ),
            pydantic.AfterValidator(
                lambda v: (
                    v
                    if isinstance(v, self.arguments)
                    else self.arguments.model_construct(**{first: v})
                )
            ),
        ]

    def call(self, arguments: pydantic.BaseModel) -> Call:
        args: list[Any] = []
        kwargs: dict[str, Any] = {}
        for p in self.parameters:
            value = getattr(arguments, p.name)
            if p.kind is p.VAR_POSITIONAL:
                args.extend(value)
            elif p.kind is p.KEYWORD_ONLY:
                kwargs[p.name] = value
            else:
                args.append(value)
        return lambda obj: self.function(obj, *args, **kwargs)
