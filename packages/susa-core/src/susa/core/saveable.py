from __future__ import annotations

from abc import abstractmethod
from collections.abc import Sequence

from typing_extensions import override

from susa.core.resource import Resource
from susa.core.serializable import JSON, Serializable, deserialize, serialize


# What has a state beyond what it's made of (e.g. a machine's memory and what it wrote to its disks).
class Saveable(Resource):
    # Leaves it as it was.
    @abstractmethod
    def save(self) -> JSON: ...

    # Creates it in the saved state.
    @abstractmethod
    def restore(self, state: JSON) -> None: ...


# Those of the resources that are serializable, as they are now (in order, so that they're created again in it).
def save(resources: Sequence[Resource]) -> JSON:
    return [
        {
            "resource": serialize(resource),
            "state": resource.save() if isinstance(resource, Saveable) else None,
        }
        for resource in resources
        if isinstance(resource, Serializable)
    ]


# Resources `save` saved, created again as they were. They keep their names, so the saved ones must be gone first.
class SavedResources(Resource):
    def __init__(self, saved: JSON) -> None:
        self.saved = saved
        self.resources: list[Resource] = []

    @override
    def create(self) -> None:
        assert not self.resources and isinstance(self.saved, list)
        try:
            for entry in self.saved:
                assert isinstance(entry, dict)
                resource = deserialize(entry["resource"])
                assert isinstance(resource, Resource)
                if isinstance(resource, Saveable):
                    resource.restore(entry["state"])
                else:
                    resource.create()
                self.resources.append(resource)
        except BaseException:
            self.destroy()
            raise

    @override
    def destroy(self) -> None:
        while self.resources:
            self.resources.pop().destroy()
