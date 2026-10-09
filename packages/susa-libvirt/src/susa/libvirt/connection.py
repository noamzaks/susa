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
        self.start_event_loop()
        self.conn = lv.open(self.uri)
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
        return Connection.current_to, (self.conn.getURI(),)

    @staticmethod
    def current() -> Connection:
        if not Connection._open:
            raise ValueError("There's no open libvirt connection!")
        return Connection._open[-1]

    @staticmethod
    def current_to(uri: str) -> Connection:
        current = Connection.current()
        # Sanity.
        assert current.conn is not None and current.conn.getURI() == uri
        return current

    # Streams (e.g. serial consoles) only receive data with an event loop, which has to be registered before
    # connections are opened.
    @staticmethod
    @functools.cache
    def start_event_loop() -> None:
        lv.virEventRegisterDefaultImpl()
        threading.Thread(target=Connection.run_event_loop, daemon=True).start()

    @staticmethod
    def run_event_loop() -> None:
        while True:
            lv.virEventRunDefaultImpl()
