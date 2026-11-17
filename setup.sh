#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
if command -v uv >/dev/null 2>&1; then
  uv sync --frozen --extra dev
  uv run deck-forge doctor
else
  python3 -m venv .venv
  .venv/bin/python -m pip install -e '.[dev]'
  .venv/bin/deck-forge doctor
fi
printf '\nReady. Open this repository with your agent and ask it to read AGENTS.md and build a deck from your material folder.\n'
