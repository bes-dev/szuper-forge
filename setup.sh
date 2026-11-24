#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
# Source archives may omit the skill-discovery symlink included in Git checkouts.
if [[ ! -e .claude/skills && ! -L .claude/skills ]]; then
  mkdir -p .claude
  ln -s ../.agents/skills .claude/skills
fi
if command -v uv >/dev/null 2>&1; then
  uv sync --frozen
  uv run --frozen szuper-forge doctor
else
  python3 -m venv .venv
  .venv/bin/python -m pip install -e .
  .venv/bin/szuper-forge doctor
fi
printf '\nReady. Open this repository with your agent and ask it to read AGENTS.md and build a deck from your material folder.\n'
