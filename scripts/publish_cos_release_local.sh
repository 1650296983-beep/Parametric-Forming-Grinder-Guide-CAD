#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON_BIN:-$ROOT/.venv/bin/python}"
TAG="${1:-}"

if [[ -n "$TAG" && "$TAG" != --* ]]; then
  shift
else
  TAG=""
fi

if [[ ! -x "$PYTHON" ]]; then
  echo "Python environment not found: $PYTHON" >&2
  exit 1
fi

if [[ " $* " != *" --dry-run "* ]]; then
  if ! "$PYTHON" -c "import qcloud_cos" >/dev/null 2>&1; then
    "$PYTHON" -m pip install -r "$ROOT/requirements-cos-publish.txt"
  fi
fi

command=("$PYTHON" "$ROOT/scripts/publish_github_release_to_cos.py")
if [[ -n "$TAG" ]]; then
  command+=(--tag "$TAG")
fi
command+=("$@")

exec "${command[@]}"
