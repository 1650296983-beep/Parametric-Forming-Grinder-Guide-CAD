# 002 — Bind the workbench to one input snapshot and actual drawing progress

- **Status**: DONE — implemented and verified; see `verification.md`
- **Base commit**: 433c974
- **Severity**: HIGH
- **Category**: State indication, interruption, accessibility and layout continuity
- **Estimated scope**: App integration, extracted workbench/hook/canvas modules, CSS, API types

## Problem

`frontend/src/App.tsx:172` accepts late responses without checking the input snapshot:

```tsx
const result = await api.validate(design);
setValidation(result);
setStep(2);
```

`Workspace` switches three unrelated layouts between input/review/generation. `SectionRelationshipDiagram` creates a generic CSS shape, and `Generation` marks all stages waiting until the request ends, then marks all complete or the last one failed. `frontend/src/styles.css` defines repeated scanning:

```css
animation: cad-scan 1.55s cubic-bezier(.4, 0, .2, 1) infinite;
```

This neither displays true progress nor lets operators inspect opening/reliefs/side-wheel defects. Min-width 1024 and three-column review cause overflow on compact screens. Raw task detail requests have a similar late-response race.

## Target

Preserve input → review → result and all existing navigation/settings/desktop file security. Implement the visual system in `design-spec.md` and exact contract in `workbench-contract.md`. Keep one left parameter/result rail, one large right actual-geometry canvas, one bottom action area in the same positions through all three steps. Task data, calculated values and scenes come exclusively from the Python API.

Shared motion tokens, following `优化动画/AUDIT.md`:

```css
--ease-out: cubic-bezier(0.23, 1, 0.32, 1);
--ease-in-out: cubic-bezier(0.77, 0, 0.175, 1);
--ease-drawer: cubic-bezier(0.32, 0.72, 0, 1);
--press-duration: 120ms;
--color-duration: 140ms;
--drawer-enter: 220ms;
--drawer-exit: 160ms;
```

Pointer-only button press feedback scale(.98), transform 120ms strong ease-out, color140ms ease. Keyboard focus/navigation/submission have no movement or delayed activation. Drawer enter opacity + translateX(12px) to0 at220ms drawer curve, exit160ms ease-out. Use transitions/mounted state so it can reverse mid-animation. SVG scene group entrance can use wrapper opacity from0→1 at160ms, outline/cavity/dimensions follow REAL backend stages only; never run a timer to pretend geometry or stages exist. No infinite scan/spinner wipe, fake percentage, looping erase/redraw, bounce or number rolling. If generation completes fast, show the final result immediately. Fit/zoom/pan are direct, no tween. For reduced motion drop translation/scale, retain color140ms/opacity120ms feedback. Gate pointer movement behind `(hover:hover) and (pointer:fine)` and explicit pointer press state (not plain `:active` that also fires on keyboard).

## Repo conventions to follow

- React18 + Vite, no external state or animation libraries. Extend existing font families (Segoe/Microsoft YaHei/PingFang and monospace). Keep desktop app Tauri `invoke`, open/save dialogs, loopback file source guard, filesystem save and updater/restart controls.
- `api.ts` owns base URL discovery and absolute normalization. Add job methods and optional AbortSignal to request wrappers. New progress.result URLs must normalize recursively, including scenes/text remaining data-only.
- Backend plan001 owns every CAD formula and real primitive. Frontend may convert points to SVG commands, fit view bounds and transform pointer coordinates; no duplicate slot/R/relief/wheel calculation.
- Existing `ArtifactActions` already distinguishes opening original vs saving copies. Preserve this behavior and security checks.

## Steps

1. Extract focused modules: workbench layout/parameter rail, actual `DrawingCanvas`, generation stage list, and a request lifecycle hook. Keep App shell/navigation/history/settings integration readable; remove dead generic CSS shape/scan code. No giant replacement App component.
2. Bind validation to a canonical snapshot/fingerprint and monotonically increasing request generation, plus AbortController. Any edit/machine/new-task/copy invalidates previous validation and generation display synchronously; late success/error/finally must not alter the new draft. Do the same for history detail loads. Preserve raw spec strings.
3. Use validated snapshot for POST jobs, never whatever is currently in a mutable form. Prevent double click submissions with a synchronous ref lock. Poll only matching taskId+snapshot. Stop polling when changing draft/unmount; don't cancel backend job. Preserve current job when merely navigating tabs; history remains available. If polling fails, offer reconnect/retry for same task, do not mark generation failed without backend evidence. Refresh history on terminal status. A task change must reset per-file action state via keys where necessary.
4. Input rail: select machine, distinct finished/preform shape and raw specs, tolerance guidance, relief field with diameter/R explanation, wheelradius and current process options. Do not infer shape from spec or change calculation rules. Keep the right canvas as an honest empty state until a current backend scene exists; after returning to edit, old preview must be hidden or explicitly marked outdated and cannot enable generation.
5. Review rail: show actual slot width+tolerance, thickness, center opening (30% with actual machine cap, floor0.01), side relief diameter + radius + count separate from fixed two centerR0.50, wheelradius, R source/direction, actual specs and backend named parsed values when available. All numbers2decimals. Backend warnings remain visible. Clearly say parameter preview, not formally released. Bottom action returns to edit or generates from reviewed snapshot.
6. Canvas: render contract data safely as SVG (never dangerouslySetInnerHTML); CAD native colors thin white outline/green cavity/cyan dimension/red center. Equal scale x/y, no CSS invented cavity. Multiple views/tabs from scene views support section1/section2/assembly after generation. Support +/- keyboard accessible zoom, wheel zoom and pointer-capture pan, fit/reset. Ignore extra pointers; release capture correctly. Keep toolbar/legend/hints readable and zoom state announced only on user action. Scene title/source accurately indicates preview/debug/released and task identity; final release scene from actual final DXF.
7. Generation rail: actual current stage/message/events; completed/running/failed status from backend. Group scene visibility follows data that already exists, never synthetic progress. Timer can show elapsed time separately, with no whole-panel aria-live every second. Stage aria-live only when changed; no fake percent. Failure keeps specs and actual failing stage, returns to edit and focuses useful field (input/parse errors → relevant spec/relief); don't delete input. Pending requests cannot attach old results.
8. Result rail: success only when ok+release_allowed true. Formal DXF/DWG open+save primary using existing ArtifactActions; debug/reports in details secondary. Show gate summary and taskID. Input→review→generate→result uses same canvas position and bottom bar. Keep historical task data separate, add `复制为新任务` action using stored input snapshot; revalidate copied input before generation. History drawer focus trap, Escape close, return focus, accessible label; rapid close/open transition interruptible.
9. CSS tokens and responsive: exact concept palette/spacing/type. Desktop review at1440×960, actually test at1280×720; rail width320–360, main canvas min-width0. Independent rail scroll while bottom action accessible. Compact laptop width≥1050 keeps side rail; narrow screens stack rail/canvas and compact nav. At390px no page horizontal overflow, buttons/fields useful and primary action reachable. Existing history/templates/settings also must avoid new overflow. Do not add marketing/fake metrics/features.
10. Update frontend types/api to contract, keep old generate method if other callers need it. Root has added `CAD_API_PROXY_TARGET` to Vite config and bumped versions to1.2.0-dev; don't overwrite those. Build and inspect for stale hook effects, response races and visual/state resets. Coordinator will perform real browser QA and integrate backend.

## Boundaries

Frontend files only, apart from version/package version and vite.config.ts owned by root. You MAY change markup/layout and extract components as explicitly specified. Do not edit Python, templates/manufacturing configs, frozen regressions, release publisher, signing or instructions. No new dependencies, no fake result or test-only app mode. No push/tag/publication. Do not commit until coordinator asks. If a contract field is unavailable, ask coordinator/backend agent rather than fabricate a calculation.

## Verification

- `cd frontend && npm run build`; expected no TypeScript failures or significant new bundle growth; `npm audit --audit-level=low`.
- Browser flow: new task → raw specs → calculate → true scene and actual opening → generate → real stage/geometry updates → gated result → open/save controls; do not invoke system CAD during automated QA unless intentionally testing.
- Change spec/new task while validation is in flight: old response cannot advance steps or reenable generation. Double generate click creates one job. History copy creates independent editable draft, never reuses released validation. Disconnect/reconnect polling retains task identity.
- Feel-check repeated pointer presses versus keyboard immediate action, interrupted drawer close/open, direct canvas zoom/pan, and reduced-motion movement removal. No animation blocks action or waits before final result.
- Done when source uses actual API/geometry, stable workbench matches concept with data-driven deviations documented, core flows build and browser verification passes.
