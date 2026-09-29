from __future__ import annotations

import logging
from abc import abstractmethod
from typing import Any, ClassVar, Generic, TypeVar

import libvirt as lv
import pydantic
from pydantic_core import core_schema
from typing_extensions import TypedDict

from susa.libvirt.connection import Connection
from susa.libvirt.model import Model
from susa.utilities.schema import instance_schema

T = TypeVar("T")
M = TypeVar("M", bound=Model[Any])

NOT_FOUND = (lv.VIR_ERR_NO_DOMAIN, lv.VIR_ERR_NO_NETWORK, lv.VIR_ERR_NO_DOMAIN_SNAPSHOT)


class LVEntityState(TypedDict, Generic[M]):
    uri: str
    model: M


class LVEntity(Generic[T, M]):
    state_type: ClassVar[Any]

    def __init__(self, model: M, conn: lv.virConnect | None = None) -> None:
        self.conn = conn or Connection.current_conn()
        self.model = model
        self.value: T | None = None

    def build(self) -> str:
        xml = self.model.build()
        logging.info(xml)
        return xml

    @abstractmethod
    def lookup(self) -> T: ...

    # Entities are pickled and serialized (as pydantic types) by their state, which reconnects to the libvirt object
    # (on the current connection), e.g. in another process.

    def __getstate__(self) -> LVEntityState[M]:
        return {
            "uri": self.conn.getURI(),
            "model": self.model,
        }

    def __setstate__(self, state: LVEntityState[M]) -> None:
        self.conn = Connection.current_conn()
        # Sanity.
        assert self.conn.getURI() == state["uri"]
        self.model = state["model"]
        try:
            self.value = self.lookup()
        except lv.libvirtError as e:
            if e.get_error_code() not in NOT_FOUND:
                raise
            self.value = None

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source: Any, handler: pydantic.GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        def restore(state: LVEntityState[M]) -> LVEntity[T, M]:
            entity = cls.__new__(cls)
            entity.__setstate__(state)
            return entity

        state = handler.generate_schema(cls.state_type)
        return instance_schema(
            cls,
            core_schema.no_info_after_validator_function(restore, state),
            lambda entity: entity.__getstate__(),
            state,
        )
