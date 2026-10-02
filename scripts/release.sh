#!/bin/sh
# Builds the distributions into dist/, with the generated files they ship.
set -e
cd "$(dirname "$0")/.."
uv run python -m susa.recipes
uv build
