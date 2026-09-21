from abc import ABC, abstractmethod
from types import TracebackType
from typing import Self

import libvirt as lv

from susa.libvirt.connection import Connection


class Entity[T](ABC):
    def __init__(self, xml: str, conn: lv.virConnect | None = None):
        self.conn = conn or Connection.current_conn()
        self.xml = xml
        self.value: T | None = None

    @abstractmethod
    def create(self) -> None: ...

    @abstractmethod
    def destroy(self) -> None: ...

    def __enter__(self) -> Self:
        assert self.value is None

        self.create()

        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        assert self.value is not None

        self.destroy()

        self.value = None
