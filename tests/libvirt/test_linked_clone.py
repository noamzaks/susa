from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from susa.libvirt.linked_clone import LinkedClone


@pytest.mark.skipif(shutil.which("qemu-img") is None, reason="There's no qemu-img")
def test_linked_clone(tmp_path: Path) -> None:
    base = tmp_path / "base.qcow2"
    subprocess.run(["qemu-img", "create", "-q", "-f", "qcow2", base, "1M"], check=True)
    clone = LinkedClone(tmp_path / "clone.qcow2", base)
    assert not clone.path.exists()

    with clone:
        info = subprocess.run(
            ["qemu-img", "info", "--output=json", clone.path],
            capture_output=True,
            check=True,
        ).stdout
        assert json.loads(info)["backing-filename"] == str(base)
    assert not clone.path.exists()
