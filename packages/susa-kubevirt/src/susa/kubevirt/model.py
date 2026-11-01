from __future__ import annotations

from typing_extensions import Self

from susa.kubevirt._kubectl import Manifest


class KVModel:
    manifest: Manifest

    def name(self, name: str) -> Self:
        self.manifest["metadata"]["name"] = name

        return self

    def get_name(self) -> str:
        name: str = self.manifest["metadata"]["name"]
        return name
