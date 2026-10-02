from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from typing_extensions import Self, TypeVar, override

from susa.core.resource import Resource
from susa.recipes import Recipe, load, make

T = TypeVar("T", default=Any)


# Objects used together, by name (e.g. a network, a machine on it and a shell on the machine), whose resources are
# created in order and destroyed in reverse.
class Session(Resource):
    def __init__(self, **objects: Any) -> None:
        self.objects = objects
        self.created: list[Resource] = []

    # An array of named recipes (or a JSON file of one), `[{"<name>": recipe}, ...]`, added in order.
    @classmethod
    def parse(cls, recipe: Sequence[Recipe] | Path) -> Self:
        session = cls()
        for entry in load(recipe):
            [(name, value)] = entry.items()
            session.add(name, value)
        return session

    # Made from a recipe whose references are to the session's objects (as they're made, before they're created).
    def add(self, name: str, recipe: Recipe) -> Any:
        if name in self.objects:
            raise ValueError(f"There's already a {name!r}")
        self.objects[name] = make(recipe, **self.objects)
        return self.objects[name]

    def get(self, name: str, cls: type[T] = object) -> T:  # type: ignore
        result = self.objects[name]
        if not isinstance(result, cls):
            raise TypeError(
                f"{name} is a {type(result).__name__}, not a {cls.__name__}"
            )
        return result

    @override
    def create(self) -> None:
        assert not self.created
        try:
            for resource in self.objects.values():
                if isinstance(resource, Resource):
                    resource.create()
                    self.created.append(resource)
        except BaseException:
            self.destroy()
            raise

    @override
    def destroy(self) -> None:
        while self.created:
            self.created.pop().destroy()
