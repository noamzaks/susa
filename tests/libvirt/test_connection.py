from __future__ import annotations

import threading

import pytest

from susa.libvirt.connection import Connection


# Only while connections are open.
def test_event_loop() -> None:
    threads = threading.active_count()
    with Connection("test:///default"), Connection("test:///default"):
        assert threading.active_count() == threads + 1
    assert threading.active_count() == threads
    with Connection("test:///default"):
        assert threading.active_count() == threads + 1
    assert threading.active_count() == threads


def test_default_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIBVIRT_DEFAULT_URI", "test:///default")
    with Connection() as connection:
        assert connection.conn is not None
        assert connection.conn.getURI() == "test:///default"


def test_uri_variable() -> None:
    with Connection.URI.set("test:///default"), Connection() as connection:
        assert connection.conn is not None
        assert connection.conn.getURI() == "test:///default"
