# Local workbench acceptance — 2026-10-20

Base release: `433c974` / `v1.1.8`. UI development: `1.2.0-dev`, local only. This document records completed verification; it is not a publication instruction.

## Automated checks

- Full Python suite: **380 passed** in 172.34 s (`output/ui-workbench/pytest-final.log`). New workbench coverage: 29 tests; existing API/runtime checks remain passing.
- Seven machine regressions: **7/7 PASS** (`output/ui-workbench/regressions-final.log` and `regression-summary-final.json`). The generated tracked summary was restored after preserving the result outside fixtures.
- All **42 frozen expected files** match the pre-repair recorded SHA256 manifest; no expected CAD, preview or report was rewritten for this UI implementation.
- Final `npm run build`: TypeScript and Vite passed, JS 199.07 kB / gzip 64.80 kB. `npm audit --audit-level=low`: zero vulnerabilities. No new frontend dependency.
- `scripts/check_versions.py`: all application version sources agree on `1.2.0-dev`; updater key unchanged. `git diff --check` passed.
- Actual macOS frozen PyInstaller sidecar built and ran. Narrow double-head up/up and up/down release smoke checks passed with 17/15 native dimensions respectively, maximum definition-point error 0.0 mm; incompatible narrow relief case rejected. This is not an interactive Windows installer or new Windows UI test.

## Browser and frozen-engine flow checks

Actual browser at local Vite with the real frozen sidecar, not a fake API or drawing:

- Single-guide block sample: slot 8.56, thickness 2.22, opening 2.00; native slot, thickness, opening, external dimensions and six relief arcs remain visible in actual DXF-derived scene.
- Triple-double down/up/up narrow block: slot 3.03, thickness 1.05, opening 0.90, side relief 4 × Ø1.00 / R0.50 and fixed center 2 × R0.50. Frozen task `4bc54b60a80f` passed, with section 1/2, side 1/2 and assembly views; scene source `release_dxf`.
- Generate double clicks create only one new task and stay in generation. Fixed a discovered second-click hit on the repositioned back button by retaining a disabled primary action and guarding repeat clicks/keys across state changes. Final single task `e6b75ba2abb4` and dual task `4bc54b60a80f` each created exactly once.
- While single task `e6b75ba2abb4` was running, gracefully stopped HTTP service. UI showed `等待恢复连接`, `进度连接中断`, same task ID, and no formal actions. Worker completed its persisted task. Restarted the same frozen sidecar and clicked reconnect: same ID, passed release, online status restored, **18 s actual generation duration**, no resubmission.
- Invalid slot 2.53 with 4-1 relief displays the engine rejection at the visible rail top and footer, retains input, offers no formal output.
- Edited/new draft during in-flight validation cannot receive the old result. History copy creates an independent unvalidated draft; delayed history detail cannot attach to another selected task.
- History drawer focus trap, Shift+Tab loop, Escape close and return focus verified. Browser DXF save reached default-download success feedback. Native Windows AutoCAD launch/save/update was not exercised here.
- Canvas actual detail fit, dimensions toggle, direct fit/zoom/pan, keyboard =/0 and wheel tested; wheel does not scroll the surrounding desktop page. Drawing never receives synthetic geometry or injected SVG markup.
- Actual 1536×1024, 1280×720 and 390×844 viewport checks. At 390, body and document widths are exactly 390 px, no horizontal page overflow; history table scroll is local. Footer actions remain reachable. Final browser warning/error log was empty; earlier deliberate 422 and service interruption were expected checks.

## Visual and motion comparison

Compared generated concept and final rendered screenshots with `view_image`:

1. Navy navigation, white header, three-step strip and persistent footer preserve the selected composition.
2. Same white parameter rail and dominant dark CAD canvas, independent rail scrolling and responsive widths.
3. Chinese system typography, 28 px primary slot value and monospace dimensional hierarchy preserved.
4. Cool gray background, navy actions, dark grid, white/green/cyan/red CAD semantic colors preserved.
5. Thin dividers, 6 px panel corners, compact spacing and consistent outline SVG icons preserved.
6. Existing five navigation labels and calculation/opening/relief copy preserved. Result state adds actual task identity, release gate and file actions in the same layout.

Required differences: concept illustration had fabricated holes/profile and example 8.57; implementation uses actual DXF shape and computed 8.56. Real native drawing dimensions take precedence over illustrative spacing. Added actual source/task status, detail fit and dimension visibility control because these support inspection without changing drawing content.

Pointer press feedback: scale .98 / 120 ms, color 140 ms. Drawer enter 220 ms / exit 160 ms, interruptible. Newly available actual scene groups fade 160 ms with bounded 0/40/80 ms offsets; released geometry appears immediately. No artificial percentage, looped scanning, drawing erasure, mandatory animation wait or bounce. Reduced-motion source branch removes transforms and delays and retains 120 ms opacity; OS preference switching was reviewed in source, not runtime-emulated.

## Evidence locations

- Concept: `output/ui-workbench/concept.png` in retained local worktree.
- Browser task persistence: `output/ui-workbench/browser-task-verification.json`.
- Screenshots: `/Users/wrd/.codex/visualizations/2026/10/20/01a15721-0ba7-7c80-b905-91158b462c5b/cad-workbench/` — `workbench-result-final.png`, `workbench-cavity-final.png`, `mobile-result-final.png`, `connection-interrupted-final.png`, `connection-recovered-final.png`.
- Local preview: `http://127.0.0.1:5288`, backend loopback 18107, isolated task data under retained worktree `output/ui-workbench/app-data`.

Manufacturing configuration, frozen expected files, release publisher and signing policy are unchanged by this UI work. Stable COS was independently re-read as `1.1.8` after all local changes.
