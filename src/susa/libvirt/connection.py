from __future__ import annotations

import threading
from types import TracebackType
from typing import ClassVar

import libvirt as lv


class Connection:
    # The innermost open connection is the current one.
    _open: ClassVar[list[Connection]] = []
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
        Connection._open.append(self)

        return self.conn

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

    @staticmethod
    def current_conn() -> lv.virConnect:
        if not Connection._open:
            raise ValueError("There's no open libvirt connection!")

        conn = Connection._open[-1].conn
        assert conn is not None
        return conn

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
