# Desktop packaging and signed GitHub Releases

This document is the release runbook for **Parametric-Forming-Grinder-Guide-CAD**.
The desktop shell does not change CAD geometry or process rules: React remains
the UI, Python remains the only CAD business implementation, and every formal
DXF/DWG remains behind the existing release gate.

## Runtime architecture

1. Tauri enforces a single desktop instance.
2. It starts the PyInstaller **onedir** executable from its read-only resources.
3. The sidecar binds an OS-selected free port on `127.0.0.1` only, writes a
   one-use status file, and serves `/api/health`.
4. Tauri waits for a successful health response before exposing the API base
   URL to React. Production fetches never use the Vite proxy.
5. On quit, Tauri requests `/api/desktop/shutdown`, waits for graceful Uvicorn
   shutdown, and force-kills only as a fallback. The Settings page can restart
   an abnormally exited engine.
6. Windows release builds use the GUI subsystem, and both the Tauri process and
   Python sidecar run without a console window.

The localhost service has one local administrator and no login database,
password, session token, device authorization, offline licence, or remote
account control. It never uploads tasks, drawings, reports, previews, settings,
logs, or history.

## Windows development environment

Install:

- Windows 10/11 x64;
- Python 3.11 x64;
- Node.js 22;
- Rust stable MSVC through `rustup`;
- Visual Studio Build Tools with “Desktop development with C++” and Windows SDK;
- NSIS prerequisites installed automatically by Tauri as needed.

From PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-packaging.txt
cd frontend
npm ci
cd ..
.\packaging\windows\build_windows.ps1 -Python .\.venv\Scripts\python.exe
```

The script checks versions, runs Python tests and all seven regressions, builds
and health-checks the onedir sidecar, builds/audits React, and creates the NSIS
installer. `-SkipTests` is for iterative local packaging only and must never be
used for a release.

Before configuring or exercising the signed release workflow, run the
`Validate Windows desktop package` workflow manually from the GitHub Actions
page on the proposed commit. It performs the same Python, regression, frontend,
PyInstaller, sidecar, and NSIS checks on `windows-latest`, but explicitly sets
`createUpdaterArtifacts=false`. It uploads the test Setup.exe, build summary,
and SHA-256 as a 14-day Actions Artifact. It has read-only repository
permissions, reads no signing Secrets, and cannot create or modify a Release.

## Python sidecar build and smoke test

```bash
./.venv/bin/python -m pip install -r requirements-packaging.txt
./.venv/bin/python -m PyInstaller --noconfirm --clean \
  packaging/pyinstaller/forming_grinder_cad.spec
./.venv/bin/python scripts/smoke_sidecar.py \
  dist/forming_grinder_cad_sidecar/forming_grinder_cad_sidecar
```

Append `.exe` on Windows. The spec includes all `templates/` assets,
Matplotlib data/fonts, and required ezdxf/Uvicorn hidden imports. It uses
`console=False`; port discovery therefore uses a status file instead of stdout.
The smoke test uses a Chinese data path, verifies `/api/health`, and verifies
that the process exits.

## macOS local application

```bash
PYTHON_BIN=./.venv/bin/python ./packaging/macos/build_macos.sh
```

The local application is written to:

```text
src-tauri/target/release/bundle/macos/Forming Grinder CAD.app
```

This local build disables updater artifact creation because it is not a public
release. The script applies an ad-hoc signature to the complete bundle after
the Python sidecar is copied. It is not Developer-ID notarized; macOS may
require an explicit local Open action on another Mac.

## Local user data

Windows mutable data is stored outside the installer:

```text
%LOCALAPPDATA%\FormingGrinderCAD\
  tasks\
  output\
  temp\
  logs\
  settings.json
```

macOS uses `~/Library/Application Support/FormingGrinderCAD/`. Source
development retains `output/web_tasks/`. `CAD_APP_DATA_ROOT` is available only
as a test/development override. On first desktop start, legacy
`output/web_tasks` directories are copied without deleting the originals or
overwriting same-named destination tasks. A migration marker prevents repeated
copies. Temp cleanup touches only `temp/`, never `tasks/` or `output/`.
Desktop task retention defaults to `0` (long-term retention); source development
keeps the historical 30-day default. An explicit positive
`CAD_TASK_RETENTION_DAYS` remains available for managed local deployments.

NSIS uses `currentUser` installation. Uninstalling, updating, or reinstalling
the application directory does not target `%LOCALAPPDATA%\FormingGrinderCAD`.
To verify preservation, create a task, record its task ID and file hashes,
upgrade/uninstall-reinstall, then confirm the same directory and hashes remain.

Generated DXF, DWG, PNG, JSON, and report files remain in the task directory
until the user explicitly deletes that task. The UI “另存为” action opens the
native save dialog, writes only to the user-selected destination, and displays
the completed path. Canceling the dialog leaves the task copy unchanged.

## AutoCAD detection and AC1021 conversion

Windows detection order is:

1. `CAD_AUTOCAD_CORE_CONSOLE`, then the path saved from Settings;
2. AutoCAD registry entries in HKLM/HKCU, including 32-bit registry locations;
3. `Program Files\Autodesk\AutoCAD 20xx\AcCoreConsole.exe`;
4. `AcCoreConsole` on `PATH`.

Automatically discovered installations are sorted newest first. macOS keeps
the existing `/Applications/Autodesk/AutoCAD *.app/.../AcCoreConsole` lookup.
Settings shows the selected version/path and lets the user choose a different
executable.

Conversion uses a subprocess argument array, a temporary staging directory,
hidden Windows console flags, and a 120-second timeout. It accepts only a DXF
whose report has `release_allowed=true`; it requires a non-empty output and an
`AC1021` header. A missing/failing AutoCAD installation records a readable
reason while leaving the validated DXF available.

## Update signing keys

Generate a key pair once on a trusted machine:

```bash
cd frontend
npx tauri signer generate --write-keys /secure/offline/FormingGrinderCAD.key
```

Commit only the `.pub` content to `plugins.updater.pubkey` in
`src-tauri/tauri.conf.json`. Never commit the private key, password, PFX, PAT,
or GitHub token. This workspace's encrypted private key is stored locally at
`/Users/wrd/.tauri/FormingGrinderCAD.key`; its password is in the macOS Keychain
service `FormingGrinderCAD-Tauri-Updater`. Move/backup both to approved secure
storage before the first public release.

Configure repository Secrets:

- `TAURI_SIGNING_PRIVATE_KEY` — complete encrypted private-key content;
- `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` — its password;
- optional `WINDOWS_CERTIFICATE` — base64 PFX for Authenticode;
- optional `WINDOWS_CERTIFICATE_PASSWORD` — PFX password.

Losing the updater private key is not recoverable for installed clients: a new
key cannot sign an update trusted by them. Restore the backed-up key or ship a
manually installed replacement client through an independently trusted channel.

## Signed one-click update flow

`bundle.createUpdaterArtifacts=true` makes Tauri sign updater artifacts. The
Windows client checks the public GitHub `latest.json`, displays version, notes,
date and progress, verifies the signature with the committed public key,
installs, and relaunches. Offline/update failures never stop local CAD work and
never remove the old version. Unsigned or invalidly signed installers are
rejected by the official updater plugin.

The default endpoint is:

```text
https://github.com/1650296983-beep/Parametric-Forming-Grinder-Guide-CAD/releases/latest/download/latest.json
```

Anonymous GitHub Release downloads require a public repository (or a public
binary-release repository). For a private source repository, publish binaries
to a separate public release repository or build a secure download service.
Never embed a GitHub PAT in the client.

For clients in the Chinese mainland, mirror the exact signed installer,
signature, and `latest.json` to a public HTTPS object-storage origin such as
Alibaba Cloud OSS or Tencent Cloud COS. Use a dedicated download domain, keep
versioned installers immutable, and update `latest.json` only after every
mirrored object is available. The mirror needs no account system or task-data
service: Tauri still verifies the installer with the public key embedded in the
client. Do not use an untrusted third-party GitHub proxy as an update endpoint.
When a mainland mirror is configured, put its endpoint before GitHub for the
next client release and retain GitHub as the public source of record.

## Versioning and publishing v1.0.0

Versions must agree in `frontend/package.json`, `src-tauri/tauri.conf.json`,
`src-tauri/Cargo.toml`, and `desktop/version.py`:

```bash
./.venv/bin/python scripts/check_versions.py --tag v1.0.0
```

Use SemVer: patch for compatible fixes, minor for compatible features, major
for breaking changes. Stable updates are tag-triggered; normal pushes and PRs
never publish a customer update.

First release steps:

1. Securely back up the updater private key and password.
2. Add required GitHub Secrets and, optionally, Authenticode Secrets.
3. Confirm the repository or binary release repository is publicly readable.
4. Run all acceptance commands below on a clean commit.
5. Manually run `Validate Windows desktop package` for that commit, download
   the Actions Artifact, verify its SHA-256, and complete the Windows VM checks.
6. Confirm `scripts/check_versions.py --tag v1.0.0` succeeds.
7. Commit the single desktop-release change; do not change `expected_*` files.
8. Create and push only the approved tag:

   ```bash
   git tag -a v1.0.0 -m "Forming Grinder CAD v1.0.0"
   git push origin v1.0.0
   ```

9. The Windows workflow checks the exact tag SHA, then creates a **draft**
   Release. Inspect test summary, attestation, `SHA256SUMS.txt`, installer,
   signature, and `latest.json` before publishing the draft.
10. On a clean Windows test VM, install, create a task, test no-update/offline,
   publish a signed test update if available, update, and confirm task hashes.
11. Publish the draft Release only after human approval.

## Rollback

Do not replace files under an existing tag. If a release is faulty, mark it as
non-latest, publish a new higher patch version containing the reverted code,
and let clients update normally. If installation itself is broken, keep the
previous installer available and provide its SHA-256; users can reinstall it
without deleting LocalAppData.

## SmartScreen and code signing

Updater signatures prove update authenticity to Tauri but do not establish
Windows publisher reputation. Without optional Authenticode Secrets, internal
test packages can be built but Windows SmartScreen may show an unknown-publisher
warning. Use an organization-controlled code-signing certificate for customer
distribution. The workflow imports it temporarily and lets Tauri sign during
bundling, before updater signatures are generated.

## Acceptance commands

```bash
./.venv/bin/python -m pytest
./.venv/bin/python scripts/run_regression_tests.py
./scripts/verify_clean_checkout.sh
cd frontend && npm ci && npm run build && npm audit --audit-level=low
```

Windows-only acceptance also includes the PyInstaller/sidecar smoke test, NSIS
build/install, Chinese Windows user name, read-only install directory, mocked
AutoCAD unit tests, signed update scenarios, restart, and LocalAppData survival.
GitHub Actions supplies build evidence, but installer/update UI scenarios still
require a clean Windows VM before publishing.

## Troubleshooting

- **Engine did not start:** use “重启本地 CAD 引擎”; inspect LocalAppData logs;
  check antivirus quarantine and sidecar resource completeness.
- **Port conflict:** ports are dynamic; a conflict usually indicates endpoint
  security software blocking localhost rather than another process on port 8000.
- **No DWG:** confirm AutoCAD is installed, reselect `AcCoreConsole.exe`, and
  keep using the validated DXF while conversion is diagnosed.
- **Cannot find an exported file:** use “另存为” on the generation result or
  history task. The native dialog chooses the destination and the row then
  displays the complete saved path.
- **Console window appears:** confirm the installer came from a release build;
  debug builds intentionally retain a console, while NSIS validation/release
  builds compile the Tauri entry point as a Windows GUI application.
- **Updater offline:** CAD remains available; retry after GitHub is reachable.
- **Signature error:** do not bypass it. Verify `latest.json`, `.sig`, public key,
  release asset URL, and signing Secret pairing.
- **SmartScreen warning:** configure Authenticode; updater signing alone does not
  remove Windows reputation warnings.
- **Missing history after upgrade:** inspect `%LOCALAPPDATA%\FormingGrinderCAD\tasks`
  before taking action; do not clear or reinstall over that directory.
