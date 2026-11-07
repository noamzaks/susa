from __future__ import annotations

import importlib
from abc import ABC, abstractmethod
from typing import TypeAlias

JSON: TypeAlias = "None | bool | int | float | str | list[JSON] | dict[str, JSON]"


# What can be passed to other processes, as pickle does (or `serialize`, as JSON): by its state, set on an instance that
# wasn't initialized.
class Serializable(ABC):
    @abstractmethod
    def __getstate__(self) -> JSON: ...

    @abstractmethod
    def __setstate__(self, state: JSON) -> None: ...


def serialize(value: Serializable) -> JSON:
    cls = type(value)
    return {
        "type": f"{cls.__module__}:{cls.__qualname__}",
        "state": value.__getstate__(),
    }


def deserialize(data: JSON) -> Serializable:
    assert isinstance(data, dict)
    name = data["type"]
    assert isinstance(name, str)
    module, qualname = name.split(":")
    cls: object = importlib.import_module(module)
    for part in qualname.split("."):
        cls = getattr(cls, part)
    assert isinstance(cls, type) and issubclass(cls, Serializable)
    result = cls.__new__(cls)
    result.__setstate__(data["state"])
    return result
