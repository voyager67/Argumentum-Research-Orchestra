#!/usr/bin/env sh
set -eu
if ! command -v ruff >/dev/null 2>&1; then
  echo "Ruff is not installed. Install the pinned development tools with: python -m pip install -e '.[dev]'" >&2
  exit 127
fi
ruff check . --output-format=concise
