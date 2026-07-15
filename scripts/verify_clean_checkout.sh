#!/usr/bin/env bash
# Verify that the committed tree, rather than machine-local ignored files, is deployable.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPORARY_ROOT="$(mktemp -d)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

cleanup() {
    rm -rf "$TEMPORARY_ROOT"
}
trap cleanup EXIT

fail() {
    echo "干净克隆验证失败：$1" >&2
    exit 1
}

cd "$PROJECT_ROOT"
git diff --quiet || fail "请先提交当前修改，再验证已提交版本。"
git diff --cached --quiet || fail "请先提交暂存修改，再验证已提交版本。"
"$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' \
    || fail "需要 Python 3.10 或更高版本；请设置 PYTHON_BIN，例如 PYTHON_BIN=python3.11。"

git archive --format=tar HEAD | tar -xf - -C "$TEMPORARY_ROOT"
for template in \
    templates/legacy_reference/section_dimension_template.dxf \
    templates/legacy_reference/standard_guide_template.dxf \
    templates/legacy_reference/R17_45XR15_8X6_2X1_65_clean_template.dxf \
    templates/legacy_reference/R17_45XR15_8X6_2X1_65_clean_template_latest.dxf \
    templates/legacy_reference/导轨长度投影（干净模板）.dxf \
    templates/legacy_reference/导轨长度，codex.dxf \
    templates/triple_double_down_up_up/full_template.dxf \
    templates/triple_double_up_up_up/full_template.dxf; do
    [[ -s "$TEMPORARY_ROOT/$template" ]] || fail "提交版本缺少 $template"
done

"$PYTHON_BIN" -m venv "$TEMPORARY_ROOT/.venv"
"$TEMPORARY_ROOT/.venv/bin/python" -m pip install --quiet -r "$TEMPORARY_ROOT/requirements.txt"
(
    cd "$TEMPORARY_ROOT/frontend"
    npm ci --ignore-scripts
    npm run build
)
(
    cd "$TEMPORARY_ROOT"
    .venv/bin/python -m pytest -q
    echo "执行独立机台回归验证…"
    .venv/bin/python scripts/run_regression_tests.py
)

echo "干净克隆验证通过。"
