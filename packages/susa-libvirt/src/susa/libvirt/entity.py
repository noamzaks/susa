from __future__ import annotations

import logging
from typing import Generic, TypeVar

from susa.libvirt.model import LVModel

M = TypeVar("M", bound=LVModel)


class LVEntity(Generic[M]):
    # Subclasses redeclare it with their model's class, which recipes would otherwise see as `M`.
    def __init__(self, model: M) -> None:
        self.model = model

    def _xml(self) -> str:
        xml = self.model.build()
        logging.info(xml)
        return xml
