from __future__ import annotations

from typing import Any

import pydantic
import pytest
from pydantic_core import core_schema
from typing_extensions import Self

from susa.utilities.recipe import recipe_schema


class Inner:
    def __init__(self) -> None:
        self.calls: list[str] = []

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source: Any, handler: pydantic.GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        return recipe_schema(cls)

    def plain(self) -> Self:
        self.calls.append("plain")
        return self


class Builder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source: Any, handler: pydantic.GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        return recipe_schema(cls)

    def plain(self) -> Self:
        self.calls.append(("plain", None))
        return self

    def one(self, value: int) -> Self:
        self.calls.append(("one", value))
        return self

    def two(self, first: str, second: int = 2, *, third: bool = False) -> Self:
        self.calls.append(("two", (first, second, third)))
        return self

    def many(self, *values: int) -> Self:
        self.calls.append(("many", values))
        return self

    def nested(self, inner: Inner) -> Self:
        self.calls.append(("nested", inner.calls))
        return self

    def not_a_step(self) -> None: ...


ADAPTER = pydantic.TypeAdapter(Builder)


def test_recipe() -> None:
    builder = ADAPTER.validate_json(
        """[
            "plain",
            {"plain": {}},
            {"one": 1},
            {"one": {"value": 2}},
            {"two": "a"},
            {"two": {"first": "b", "second": 3, "third": true}},
            {"many": [1, 2]},
            "many",
            {"nested": ["plain"]}
        ]"""
    )
    assert builder.calls == [
        ("plain", None),
        ("plain", None),
        ("one", 1),
        ("one", 2),
        ("two", ("a", 2, False)),
        ("two", ("b", 3, True)),
        ("many", (1, 2)),
        ("many", ()),
        ("nested", ["plain"]),
    ]


@pytest.mark.parametrize(
    "recipe",
    (
        ["not_a_step"],
        ["one"],
        [{"one": "a"}],
        [{"one": 1, "two": "a"}],
        [{"two": {"second": 3}}],
        [{"two": {"first": "a", "fourth": 4}}],
        [{"many": 1}],
    ),
)
def test_invalid_recipe(recipe: list[Any]) -> None:
    with pytest.raises(pydantic.ValidationError):
        ADAPTER.validate_python(recipe)


def test_recipe_json_schema() -> None:
    steps = ADAPTER.json_schema()["items"]["oneOf"]
    assert {"const": "plain", "type": "string"} in [
        choice for step in steps for choice in step.get("anyOf", [])
    ]
    assert len(steps) == 5
