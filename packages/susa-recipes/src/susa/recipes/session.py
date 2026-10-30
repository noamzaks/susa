from __future__ import annotations

import logging
from typing import Annotated, Any, TypeVar

import pydantic
from typing_extensions import Self, override

from susa.core.resource import Resource
from susa.recipes import Recipe

T = TypeVar("T")

NamedRecipe = Annotated[dict[str, Recipe], pydantic.Field(min_length=1, max_length=1)]


class Session(pydantic.BaseModel, Resource, extra="forbid"):
    schema_: str | None = pydantic.Field(None, alias="$schema")
    objects: list[NamedRecipe]
    _made: dict[str, Any] = pydantic.PrivateAttr(default_factory=dict)
    _created: list[tuple[str, Resource]] = pydantic.PrivateAttr(
        default_factory=list[tuple[str, Resource]]
    )

    @pydantic.model_validator(mode="after")
    def unique_names(self) -> Self:
        names = [next(iter(entry)) for entry in self.objects]
        if len(set(names)) != len(names):
            raise ValueError("Names must be unique")
        return self

    def __contains__(self, name: str) -> bool:
        return name in self._made

    def get(self, name: str, cls: type[T]) -> T:
        result = self._made[name]
        assert isinstance(result, cls)
        return result

    def all(self, cls: type[T]) -> list[T]:
        return [o for o in self._made.values() if isinstance(o, cls)]

    @override
    def create(self) -> None:
        assert not self._created
        try:
            for entry in self.objects:
                [(name, recipe)] = entry.items()
                made = self._made[name] = recipe.make(**self._made)
                if isinstance(made, Resource):
                    logging.info("Creating %s", name)
                    made.create()
                    self._created.append((name, made))
        except BaseException:
            self.destroy()
            raise

    @override
    def destroy(self) -> None:
        while self._created:
            name, resource = self._created.pop()
            logging.info("Destroying %s", name)
            resource.destroy()
