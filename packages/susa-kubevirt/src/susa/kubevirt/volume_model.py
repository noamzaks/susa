from __future__ import annotations

from typing_extensions import Self

from susa.kubevirt._kubectl import Manifest, random_name
from susa.kubevirt.model import KVModel


class KVVolumeModel(KVModel):
    def __init__(self, name: str | None = None) -> None:
        self.manifest = {
            "apiVersion": "cdi.kubevirt.io/v1beta1",
            "kind": "DataVolume",
            "metadata": {"name": name or random_name()},
            "spec": {"source": {"blank": {}}, "storage": {}},
        }

    def capacity(self, capacity: int) -> Self:
        self._storage["resources"] = {"requests": {"storage": str(capacity)}}

        return self

    def storage_class(self, name: str) -> Self:
        self._storage["storageClassName"] = name

        return self

    def image(self, url: str) -> Self:
        self.manifest["spec"]["source"] = {"http": {"url": url}}

        return self

    def clone(self, name: str, namespace: str = "default") -> Self:
        self.manifest["spec"]["source"] = {
            "pvc": {"name": name, "namespace": namespace}
        }

        return self

    @property
    def _storage(self) -> Manifest:
        storage: Manifest = self.manifest["spec"]["storage"]
        return storage
