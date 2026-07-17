param(
    [string]$Python = "python",
    [switch]$SkipTests
)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
Set-Location $Root

& $Python scripts/check_versions.py
& $Python -m pip install -r requirements-packaging.txt
if (-not $SkipTests) {
    & $Python -m pytest
    & $Python scripts/run_regression_tests.py
}
& $Python -m PyInstaller --noconfirm --clean packaging/pyinstaller/forming_grinder_cad.spec
$Sidecar = Join-Path $Root "dist/forming_grinder_cad_sidecar/forming_grinder_cad_sidecar.exe"
& $Python scripts/smoke_sidecar.py $Sidecar

Push-Location frontend
npm ci
npm run build
npm audit --audit-level=low
Pop-Location

if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    throw "Rust/Cargo is required. Install rustup before building Tauri."
}
& frontend/node_modules/.bin/tauri.cmd build --bundles nsis
