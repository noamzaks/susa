from __future__ import annotations

import threading
from types import TracebackType
from typing import ClassVar

import libvirt as lv


class Connection:
    _current: ClassVar[Connection | None] = None
    _event_loop_lock: ClassVar[threading.Lock] = threading.Lock()
    _event_loop_started: ClassVar[bool] = False

    def __init__(self, uri: str | None = None) -> None:
        self.uri = uri
        self.conn: lv.virConnect | None = None

    def __enter__(self) -> lv.virConnect:
        if self.conn is not None:
            raise ValueError("Cannot open an already opened connection!")

        Connection._start_event_loop()
        self.conn = lv.open(self.uri)

        if Connection._current is None:
            Connection._current = self

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

    @staticmethod
    def _start_event_loop() -> None:
        # Streams (e.g. serial consoles) only receive data with an event loop, which has to be registered before
        # connections are opened.
        with Connection._event_loop_lock:
            if Connection._event_loop_started:
                return

            lv.virEventRegisterDefaultImpl()
            threading.Thread(target=Connection._run_event_loop, daemon=True).start()
            Connection._event_loop_started = True

    @staticmethod
    def _run_event_loop() -> None:
        while True:
            lv.virEventRunDefaultImpl()
