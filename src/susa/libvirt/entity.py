from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

import libvirt as lv

from susa.libvirt.connection import Connection
from susa.libvirt.model import Model

T = TypeVar("T")
M = TypeVar("M", bound=Model[Any])

NOT_FOUND = (
    lv.VIR_ERR_NO_DOMAIN,
    lv.VIR_ERR_NO_NETWORK,
    lv.VIR_ERR_NO_STORAGE_VOL,
    lv.VIR_ERR_NO_DOMAIN_SNAPSHOT,
)


# A model, and the libvirt object made of it (`None` until it's created). It's pickled without the libvirt object,
# which it looks up again when unpickled.
class LVEntity(ABC, Generic[T, M]):
    # Entities spell this out with their model's class, which recipes would otherwise see as `M`.
    def __init__(self, model: M) -> None:
        self.connection = Connection.current()
        self.model = model
        self.value: T | None = None

    @property
    def conn(self) -> lv.virConnect:
        assert self.connection.conn is not None
        return self.connection.conn

    @abstractmethod
    def lookup(self) -> T: ...

    def xml(self) -> str:
        xml = self.model.build()
        logging.info(xml)
        return xml

    def __getstate__(self) -> dict[str, Any]:
        state = vars(self).copy()
        del state["value"]
        return state

    def __setstate__(self, state: dict[str, Any]) -> None:
        vars(self).update(state)
        self.value = None
        try:
            self.value = self.lookup()
        except lv.libvirtError as e:
            if e.get_error_code() not in NOT_FOUND:
                raise
