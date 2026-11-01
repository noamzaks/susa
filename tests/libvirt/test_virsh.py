from __future__ import annotations

import subprocess

import pytest

from susa.libvirt._virsh import URI, virsh


def test_default_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIBVIRT_DEFAULT_URI", "test:///default")
    assert virsh("uri").strip() == "test:///default"


def test_uri_variable() -> None:
    with URI.set("test:///default"):
        assert virsh("uri").strip() == "test:///default"


def test_error() -> None:
    with URI.set("test:///default"), pytest.raises(subprocess.CalledProcessError):
        virsh("dominfo", "nothing")
