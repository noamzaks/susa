from __future__ import annotations

import functools
import logging
import threading
from types import TracebackType
from typing import Any, ClassVar

from typing_extensions import Self, override

import libvirt as lv
from susa.core.variable import Variable


# Pickled as its URI, and unpickled as the current connection (which must be to the same URI).
class Connection:
    _open: ClassVar[list[Connection]] = []
    # Running while connections are open.
    _loop: ClassVar[threading.Thread | None] = None

    # `None` is libvirt's default, `LIBVIRT_DEFAULT_URI`.
    URI: ClassVar[Variable[str | None]] = Variable(None)

    def __init__(self, uri: str | None = None) -> None:
        self.uri = uri or Connection.URI.get()
        self.conn: lv.virConnect | None = None

    def __enter__(self) -> Self:
        assert self.conn is None
        if not Connection._open:
            self.start_event_loop()
        self.conn = lv.open(self.uri)
        logging.info("Connected to %s", self.conn.getURI())
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
        if not Connection._open:
            self.stop_event_loop()

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

    # Streams (e.g. serial consoles) only receive data with an event loop, which has to be registered (once) before
    # connections are opened.
    @staticmethod
    @functools.cache
    def register_event_loop() -> None:
        lv.virEventRegisterDefaultImpl()

    @staticmethod
    def start_event_loop() -> None:
        Connection.register_event_loop()
        Connection._loop = threading.Thread(
            target=Connection.run_event_loop, daemon=True
        )
        Connection._loop.start()

    @staticmethod
    def stop_event_loop() -> None:
        assert Connection._loop is not None
        loop, Connection._loop = Connection._loop, None

        # Wakes it up to see that it's stopped.
        def wake(timer: int, _: None) -> None:
            lv.virEventRemoveTimeout(timer)

        lv.virEventAddTimeout(0, wake, None)
        loop.join()

    @staticmethod
    def run_event_loop() -> None:
        while Connection._loop is threading.current_thread():
            lv.virEventRunDefaultImpl()
