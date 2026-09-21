import platform
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def fake_host_arch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform, "machine", lambda: "x86_64")


@pytest.fixture(autouse=True)
def fake_resolve(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_cwd = Path("/fake/cwd")

    def resolve(self: Path, strict: bool = False) -> Path:
        return self if self.is_absolute() else fake_cwd / self

    monkeypatch.setattr(Path, "resolve", resolve)
