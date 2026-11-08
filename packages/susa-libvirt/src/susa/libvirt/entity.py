from __future__ import annotations

import logging
from typing import Generic, TypeVar, cast

from typing_extensions import override

from susa.core.serializable import JSON, Serializable, deserialize, serialize
from susa.libvirt.model import LVModel

M = TypeVar("M", bound=LVModel)


class LVEntity(Serializable, Generic[M]):
    def __init__(self, model: M) -> None:
        self.model = model

    @override
    def __getstate__(self) -> JSON:
        return {"model": serialize(self.model)}

    @override
    def __setstate__(self, state: JSON) -> None:
        assert isinstance(state, dict)
        model = deserialize(state["model"])
        assert isinstance(model, LVModel)
        self.model = cast("M", model)

    def _xml(self) -> str:
        xml = self.model.build()
        logging.info(xml)
        return xml
