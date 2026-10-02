from __future__ import annotations

import json
from pathlib import Path

from susa.recipes import schema

# Shipped with the package (see `scripts/release.sh`).
(Path(__file__).parent / "recipe.schema.json").write_text(
    json.dumps(schema(), indent=2) + "\n"
)
