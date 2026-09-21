from abc import ABC
from types import TracebackType
from typing import Self

import libvirt as lv


class Connection:
    _current: Connection | None = None

    def __init__(self, uri: str | None = None) -> None:
        self.uri = uri
        self.conn: lv.virConnect | None = None

    def __enter__(self) -> lv.virConnect:
        if self.conn is not None:
            raise ValueError("Cannot open an already opened connection!")

        if Connection._current is None:
            Connection._current = self

        self.conn = lv.open(self.uri)
        return self.conn

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if Connection._current is self:
            Connection._current = None

        if self.conn is None:
            return

        self.conn.close()
        self.conn = None

    @staticmethod
    def current() -> Connection:
        if Connection._current is None:
            raise ValueError(
                "Cannot get current libvirt connection as there isn't any!"
            )

        return Connection._current

    @staticmethod
    def current_conn() -> lv.virConnect:
        c = Connection.current()
        assert c.conn is not None
        return c.conn
