from __future__ import annotations

import json
import pickle

from typing_extensions import override

from susa.core.serializable import JSON, Serializable, deserialize, serialize


class Point(Serializable):
    def __init__(self, x: int, y: int) -> None:
        self.x = x
        self.y = y

    @override
    def __getstate__(self) -> JSON:
        return [self.x, self.y]

    @override
    def __setstate__(self, state: JSON) -> None:
        assert isinstance(state, list)
        x, y = state
        assert isinstance(x, int) and isinstance(y, int)
        Point.__init__(self, x, y)


def test_serialize() -> None:
    data = json.loads(json.dumps(serialize(Point(1, 2))))
    assert data == {"type": "tests.core.test_serializable:Point", "state": [1, 2]}
    result = deserialize(data)
    assert isinstance(result, Point)
    assert (result.x, result.y) == (1, 2)


def test_pickle() -> None:
    result = pickle.loads(pickle.dumps(Point(1, 2)))
    assert (result.x, result.y) == (1, 2)
