from __future__ import annotations

import json
from pathlib import Path

from susa.schemas import TYPES, generate


def test_generate(tmp_path: Path) -> None:
    generate(tmp_path)
    for t in TYPES:
        schema = json.loads((tmp_path / f"{t.__name__}.schema.json").read_text())
        assert schema["title"] == t.__name__
