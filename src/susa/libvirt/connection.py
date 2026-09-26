from __future__ import annotations

import threading
from types import TracebackType

import libvirt as lv

_event_loop_lock = threading.Lock()
_event_loop_started = False


def _run_event_loop() -> None:
    while True:
        lv.virEventRunDefaultImpl()


def start_event_loop() -> None:
    """Run libvirt's default event loop in a background thread (once per process). It has to be registered
    before connections are opened, and without it streams (e.g. serial consoles) never receive data."""
    global _event_loop_started

    with _event_loop_lock:
        if _event_loop_started:
            return

        lv.virEventRegisterDefaultImpl()
        threading.Thread(
            target=_run_event_loop, name="libvirt-events", daemon=True
        ).start()
        _event_loop_started = True


class Connection:
    _current: Connection | None = None

    def __init__(self, uri: str | None = None) -> None:
        self.uri = uri
        self.conn: lv.virConnect | None = None

    def __enter__(self) -> lv.virConnect:
        if self.conn is not None:
            raise ValueError("Cannot open an already opened connection!")

        start_event_loop()
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
