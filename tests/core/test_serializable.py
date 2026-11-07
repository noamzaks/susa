from __future__ import annotations

import json
import pickle

from susa.communicators.container import ContainerCommunicator
from susa.core.serializable import deserialize, serialize


def test_serialize() -> None:
    data = json.loads(json.dumps(serialize(ContainerCommunicator(1, ["net"]))))
    assert data == {
        "type": "susa.communicators.container:ContainerCommunicator",
        "state": {"pid": 1, "namespaces": ["net"]},
    }
    result = deserialize(data)
    assert isinstance(result, ContainerCommunicator)
    assert vars(result) == {"pid": 1, "namespaces": ["net"]}


def test_pickle() -> None:
    result = pickle.loads(pickle.dumps(ContainerCommunicator(1, ["net"])))
    assert vars(result) == {"pid": 1, "namespaces": ["net"]}
