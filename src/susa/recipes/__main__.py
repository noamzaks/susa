from __future__ import annotations

import json
from pathlib import Path

import pydantic

from susa.core.session import SessionRecipe
from susa.recipes import Recipe, RecipeJsonSchema

schema = pydantic.TypeAdapter(Recipe | SessionRecipe).json_schema(
    schema_generator=RecipeJsonSchema
)
# Shipped with the package (see `scripts/release.sh`).
(Path(__file__).parent / "recipe.schema.json").write_text(
    json.dumps(schema, indent=2) + "\n"
)
