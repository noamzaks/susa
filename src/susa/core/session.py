from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import pydantic
from typing_extensions import Self, TypeVar, override

from susa.core.resource import Resource
from susa.recipes import Recipe

T = TypeVar("T", default=Any)


# `[{"<name>": recipe}, ...]`, made in order, where references are to the objects before.
class SessionRecipe(
    pydantic.RootModel[
        list[Annotated[dict[str, Recipe], pydantic.Field(min_length=1, max_length=1)]]
    ]
):
    pass


# Objects, or recipes of them, made when it's created, in order (so references are to created objects).
class Session(Resource):
    def __init__(self, **objects: Any) -> None:
        self.objects = objects
        self.created: list[Resource] = []

    @classmethod
    def parse(cls, recipe: SessionRecipe | list[Any]) -> Self:
        objects: dict[str, Recipe] = {}
        for entry in SessionRecipe.model_validate(recipe).root:
            [(name, value)] = entry.items()
            if name in objects:
                raise ValueError(f"There's already a {name!r}")
            objects[name] = value
        return cls(**objects)

    @classmethod
    def load(cls, path: Path) -> Self:
        return cls.parse(SessionRecipe.model_validate_json(path.read_bytes()))

    def get(self, name: str, cls: type[T] = object) -> T:  # type: ignore
        result = self.objects[name]
        if not isinstance(result, cls):
            raise TypeError(
                f"{name} is a {type(result).__name__}, not a {cls.__name__}"
            )
        return result

    def all(self, cls: type[T] = object) -> list[T]:  # type: ignore
        return [o for o in self.objects.values() if isinstance(o, cls)]

    @override
    def create(self) -> None:
        assert not self.created
        try:
            for name, value in self.objects.items():
                if isinstance(value, Recipe):
                    value = self.objects[name] = value.make(**self.objects)
                if isinstance(value, Resource):
                    value.create()
                    self.created.append(value)
        except BaseException:
            self.destroy()
            raise

    @override
    def destroy(self) -> None:
        while self.created:
            self.created.pop().destroy()
