from __future__ import annotations

from typing_extensions import override

from susa.core.resource import Resource
from susa.kubevirt._kubectl import create, delete, wait
from susa.kubevirt.volume_model import KVVolumeModel


class KVVolume(Resource):
    def __init__(self, model: KVVolumeModel, timeout: float = 600) -> None:
        self.model = model
        self.timeout = timeout

    @override
    def create(self) -> None:
        create(self.model.manifest)

    @override
    def destroy(self) -> None:
        delete("datavolume", self.model.get_name(), self.timeout)

    def wait_until_ready(self) -> None:
        wait("datavolume", self.model.get_name(), "condition=Ready", self.timeout)
