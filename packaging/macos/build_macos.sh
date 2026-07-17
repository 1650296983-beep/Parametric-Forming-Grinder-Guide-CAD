#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON="${PYTHON_BIN:-$ROOT/.venv/bin/python}"
cd "$ROOT"

"$PYTHON" scripts/check_versions.py
"$PYTHON" -m pip install -r requirements-packaging.txt
"$PYTHON" -m PyInstaller --noconfirm --clean packaging/pyinstaller/forming_grinder_cad.spec
"$PYTHON" scripts/smoke_sidecar.py "$ROOT/dist/forming_grinder_cad_sidecar/forming_grinder_cad_sidecar"
npm --prefix frontend ci
npm --prefix frontend run build
npm --prefix frontend audit --audit-level=low
frontend/node_modules/.bin/tauri build --bundles app --config '{"bundle":{"createUpdaterArtifacts":false}}'

APP_BUNDLE="$ROOT/src-tauri/target/release/bundle/macos/Forming Grinder CAD.app"
# Local builds have no Developer ID certificate, so seal the complete bundle
# with an ad-hoc signature after Tauri has copied the Python sidecar/resources.
codesign --force --deep --sign - "$APP_BUNDLE"
codesign --verify --deep --strict --verbose=2 "$APP_BUNDLE"
