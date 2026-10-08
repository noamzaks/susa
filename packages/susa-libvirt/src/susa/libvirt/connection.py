from __future__ import annotations

import functools
import threading
from types import TracebackType
from typing import Any, ClassVar

from typing_extensions import Self, override

import libvirt as lv


# Pickled as its URI, and unpickled as the current connection (which must be to the same URI).
class Connection:
    _open: ClassVar[list[Connection]] = []

    def __init__(self, uri: str | None = None) -> None:
        self.uri = uri
        self.conn: lv.virConnect | None = None

    def __enter__(self) -> Self:
        assert self.conn is None
        self.conn = open_connection(self.uri)
        Connection._open.append(self)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        assert self.conn is not None
        Connection._open.remove(self)
        self.conn.close()
        self.conn = None

    @override
    def __reduce__(self) -> tuple[Any, ...]:
        assert self.conn is not None
        return current_connection, (self.conn.getURI(),)

    @staticmethod
    def current() -> Connection:
        if not Connection._open:
            raise ValueError("There's no open libvirt connection!")
        return Connection._open[-1]


def current_connection(uri: str) -> Connection:
    current = Connection.current()
    # Sanity.
    assert current.conn is not None and current.conn.getURI() == uri
    return current


def open_connection(uri: str | None) -> lv.virConnect:
    start_event_loop()
    return lv.open(uri)


# Streams (e.g. serial consoles) only receive data with an event loop, which has to be registered before connections
# are opened.
@functools.cache
def start_event_loop() -> None:
    lv.virEventRegisterDefaultImpl()
    threading.Thread(target=run_event_loop, daemon=True).start()


def run_event_loop() -> None:
    while True:
        lv.virEventRunDefaultImpl()
