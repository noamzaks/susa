from __future__ import annotations

import logging
from abc import abstractmethod
from typing import Any, ClassVar, Generic, TypeVar

import libvirt as lv
import pydantic
from pydantic_core import core_schema
from typing_extensions import Self, TypedDict, override

from susa.libvirt.connection import Connection
from susa.libvirt.model import Model
from susa.utilities.serializable import Serializable

T = TypeVar("T")
M = TypeVar("M", bound=Model[Any])

NOT_FOUND = (lv.VIR_ERR_NO_DOMAIN, lv.VIR_ERR_NO_NETWORK, lv.VIR_ERR_NO_DOMAIN_SNAPSHOT)


class LVEntityState(TypedDict, Generic[M]):
    uri: str
    model: M


class LVEntity(Serializable, Generic[T, M]):
    state_type: ClassVar[Any]

    def __init__(self, model: M, conn: lv.virConnect | None = None) -> None:
        self.conn = conn or Connection.current_conn()
        self.model = model
        self.value: T | None = None

    # What's sent to libvirt.
    def xml(self) -> str:
        xml = self.model.build()
        logging.info(xml)
        return xml

    @abstractmethod
    def lookup(self) -> T: ...

    # An entity's serialized form is its state, which reconnects to the libvirt object (on the current connection),
    # e.g. in another process.

    @override
    def serialize(self) -> LVEntityState[M]:
        return {"uri": self.conn.getURI(), "model": self.model}

    @classmethod
    @override
    def serialized_schema(
        cls, handler: pydantic.GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        return core_schema.no_info_after_validator_function(
            cls.restore, handler.generate_schema(cls.state_type)
        )

    @classmethod
    def restore(cls, state: LVEntityState[M]) -> Self:
        entity = cls(state["model"])
        entity.reconnect(state["uri"])
        return entity

    def reconnect(self, uri: str) -> None:
        # Sanity.
        assert self.conn.getURI() == uri
        try:
            self.value = self.lookup()
        except lv.libvirtError as e:
            if e.get_error_code() not in NOT_FOUND:
                raise
