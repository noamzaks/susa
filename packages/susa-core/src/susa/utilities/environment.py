from __future__ import annotations

import functools
import importlib.util
import os
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from susa.recipes.session import Session

T = TypeVar("T")


# `SUSA_SESSION`'s recipe, cooked once it's first needed (if recipes are installed). Its objects are defaults by name
# (e.g. "host"), e.g. for processes started in a container's context.
@functools.cache
def session() -> Session | None:
    recipe = os.environ.get("SUSA_SESSION")
    if not recipe or importlib.util.find_spec("susa.recipes") is None:
        return None
    from susa.recipes.session import Session

    result = Session.model_validate_json(recipe)
    result.create()
    return result


def default(name: str, cls: type[T]) -> T | None:
    current = session()
    if current is None or name not in current:
        return None
    result = current.get(name, object)
    if not isinstance(result, cls):
        raise TypeError(f"SUSA_SESSION's {name!r} isn't a {cls.__name__}")
    return result
