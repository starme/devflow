#!/usr/bin/env bash
# DevFlow pre-commit gate and regression entry point.
#
# Provisions its own toolchain under .venv so local runs match CI exactly.
# A global ruff/mypy is deliberately not used: a different version would check
# different rules than pyproject.toml pins.
#
# Usage:
#   scripts/check.sh          # full gate: lint + format + type + test
#   scripts/check.sh lint     # ruff check
#   scripts/check.sh format   # ruff format --check
#   scripts/check.sh type     # mypy
#   scripts/check.sh test     # unittest suites
#   scripts/check.sh fix      # apply autofixes and formatting
set -euo pipefail

cd "$(dirname "$0")/.."

VENV=".venv"
PYTHON="$VENV/bin/python"
RUFF="$VENV/bin/ruff"
MYPY="$VENV/bin/mypy"
PYTHON_VERSION="3.11"

setup() {
  if ! command -v uv >/dev/null 2>&1; then
    echo "uv not found; install it from https://docs.astral.sh/uv/" >&2
    exit 1
  fi
  if [ ! -x "$PYTHON" ]; then
    uv venv -q -p "$PYTHON_VERSION" "$VENV"
  fi
  uv pip install -q --python "$PYTHON" ruff mypy
}

require_tools() {
  setup
}

lint() {
  require_tools
  "$RUFF" check .
}

format_check() {
  require_tools
  "$RUFF" format --check .
}

type_check() {
  require_tools
  "$MYPY"
}

test() {
  require_tools
  "$PYTHON" -m unittest discover -s core/tests
  "$PYTHON" -m unittest discover -s adapters/codex/tests
}

fix() {
  require_tools
  "$RUFF" check . --fix --unsafe-fixes
  "$RUFF" format .
}

case "${1:-check}" in
  check)  lint; format_check; type_check; test ;;
  lint)   lint ;;
  format) format_check ;;
  type)   type_check ;;
  test)   test ;;
  fix)    fix ;;
  *)
    echo "unknown target: $1" >&2
    echo "usage: $0 [check|lint|format|type|test|fix]" >&2
    exit 2
    ;;
esac
