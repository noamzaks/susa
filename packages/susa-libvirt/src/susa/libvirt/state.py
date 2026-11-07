from __future__ import annotations

import pickle
from collections.abc import Sequence
from pathlib import Path

from typing_extensions import override

from susa.core.resource import Resource
from susa.libvirt.machine import LVMachine
from susa.libvirt.volume import LVVolume


# Resources saved with their volumes and the memories of their running machines, each in the file of its index, and
# created again as they were. They keep their names, so the saved ones must be gone first.
class LVState(Resource):
    RESOURCES = "resources.pickle"

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.resources: list[Resource] = []

    @override
    def create(self) -> None:
        assert not self.resources
        resources: list[Resource] = pickle.loads(
            (self.directory / LVState.RESOURCES).read_bytes()
        )
        try:
            for index, resource in enumerate(resources):
                path = self.directory / str(index)
                if isinstance(resource, (LVMachine, LVVolume)) and path.exists():
                    resource.restore(path)
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

    # Machines that are off aren't saved, and boot from their saved volumes.
    @staticmethod
    def save(resources: Sequence[Resource], directory: str | Path) -> None:
        directory = Path(directory)
        directory.mkdir(parents=True)
        machines = {
            directory / str(i): r
            for i, r in enumerate(resources)
            if isinstance(r, LVMachine) and r.is_powered_on
        }
        for path, machine in machines.items():
            machine.save(path)
        for index, resource in enumerate(resources):
            if isinstance(resource, LVVolume):
                resource.save(directory / str(index))
        for path, machine in machines.items():
            machine.restore(path)
        (directory / LVState.RESOURCES).write_bytes(pickle.dumps(list(resources)))
