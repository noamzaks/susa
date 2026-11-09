from __future__ import annotations

import json

import pytest
from typing_extensions import override

from susa.core.resource import Resource
from susa.core.saveable import Saveable, SavedResources, save
from susa.core.serializable import JSON, Serializable

EVENTS: list[str] = []


class Thing(Resource, Serializable):
    def __init__(self, name: str) -> None:
        self.name = name

    @override
    def create(self) -> None:
        if self.name == "broken":
            raise ValueError
        EVENTS.append(f"create {self.name}")

    @override
    def destroy(self) -> None:
        EVENTS.append(f"destroy {self.name}")

    @override
    def __getstate__(self) -> JSON:
        return self.name

    @override
    def __setstate__(self, state: JSON) -> None:
        assert isinstance(state, str)
        self.name = state


class Counter(Thing, Saveable):
    count = 0

    @override
    def save(self) -> JSON:
        return self.count

    @override
    def restore(self, state: JSON) -> None:
        assert isinstance(state, int)
        self.count = state
        EVENTS.append(f"restore {self.name} {state}")


class Unserializable(Resource):
    @override
    def create(self) -> None:
        pass

    @override
    def destroy(self) -> None:
        pass


def test_saved_resources() -> None:
    counter = Counter("counter")
    counter.count = 5
    saved = json.loads(json.dumps(save([Thing("thing"), counter, Unserializable()])))
    EVENTS.clear()
    with SavedResources(saved) as restored:
        [thing, copy] = restored.resources
        assert isinstance(thing, Thing) and isinstance(copy, Counter)
        assert copy.count == 5
    assert EVENTS == [
        "create thing",
        "restore counter 5",
        "destroy counter",
        "destroy thing",
    ]


def test_saved_resources_fail() -> None:
    saved = save([Thing("thing"), Thing("broken")])
    EVENTS.clear()
    restored = SavedResources(saved)
    with pytest.raises(ValueError):
        restored.create()
    assert EVENTS == ["create thing", "destroy thing"]
