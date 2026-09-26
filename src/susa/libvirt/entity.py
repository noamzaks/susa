from __future__ import annotations

import logging
from typing import Any, Generic, TypeVar

import libvirt as lv

from susa.libvirt.connection import Connection
from susa.libvirt.model import Model

logger = logging.getLogger(__name__)

T = TypeVar("T")
M = TypeVar("M", bound=Model[Any])


class LVEntity(Generic[T, M]):
    """Something created in libvirt from the model `M`, which is kept around to get information from."""

    def __init__(self, model: M, conn: lv.virConnect | None = None) -> None:
        self.conn = conn or Connection.current_conn()
        self.model = model
        self.value: T | None = None

    def build(self) -> str:
        xml = self.model.build()
        logger.info(xml)
        return xml
