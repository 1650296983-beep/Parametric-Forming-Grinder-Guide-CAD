# 001 — Expose real geometry and actual generation stages

- **Status**: DONE — implemented and verified; see `verification.md`
- **Base commit**: 433c974
- **Severity**: HIGH
- **Category**: State indication and correctness
- **Estimated scope**: Backend adapter, CAD progress hooks, focused tests, docs

## Problem

`src/web_api.py` synchronous generation blocks until completion. `src/preview.py` simplifies the cavity and the frontend draws a generic CSS shape. `src/generate_machine.py` and `src/dual_guide_engine.py` already own actual construction and formal release promotion. Expose their real state rather than duplicating them.

## Target

Implement every backend field and endpoint in `plans/workbench-contract.md`. Preserve old API callers and CAD byte/geometry semantics. New files such as `src/drawing_scene.py` and `src/generation_progress.py` should have small explicit responsibilities. For validation, reuse actual writers or their construction functions in a disposable temporary context; do not retain/export candidate files. Only final released DXF can be represented as released. Default arbitrary spec and all 7 machines must work. Side views matter for the repaired wheel defect.

## Repo conventions to follow

`src/web_task_repository.py` persists task input/lifecycle in isolated twelve-character ID directories. `generate_design()` and `_generate_dual_guide_design()` own task initialization and completion. CLI runs in a subprocess (including frozen `generate-machine` command); dual generation currently runs in process. Pass optional scoped progress context across both without changing legacy direct CLI behavior. `WebTaskRepository._write_status` demonstrates atomic replace. Depend on local `require_user` at routes.

## Steps

1. Add a scene adapter that serializes actual ezdxf entities, virtual dimensions and arcs into the agreed contract. Group source entities rather than calculating a replacement profile. Include bounds/units/source and section/side views. Exclude old template parametric remnants via existing writer cleanup.
2. Enrich validation response with backend-derived dimensions and scene. Return helpful errors, not fabricated scene on failure.
3. Add asynchronous job initialization and bounded worker; reuse existing generator against the initialized task instead of creating a duplicate history task. Persist stages and result; preserve synchronous endpoint behavior.
4. Add small optional progress hooks at actual writer/CLI/dual construction, candidate, preview, validation and promotion boundaries. No sleeps, percentages or timer-based completion. Keep subprocess progress path scoped via its environment and in-process state scoped by context; never mutate process-global env per request.
5. Serve progress only for a validated authorized task. Persist failure at actual current stage, release_allowed false, never expose release files before successful promotion. Handle interruption/restart as interrupted rather than indefinite running.
6. Add meaningful tests for task identity/snapshot, stage order and failure, independent actual scene geometry (including 6 relief arcs and final side wheel), path isolation and sync compatibility. Update docs for the public local API and local-only UI development.

## Boundaries

Own only Python backend/source tests and related docs. Do not edit frontend, version files, plans or manufacturing configs. Do not change geometry calculations, thresholds, frozen fixtures, release gates, publisher or signing. No new dependencies. Other agent may edit frontend simultaneously in this same isolated worktree. Do not commit until coordinator asks; report exact changed files and checks.

## Verification

- `.venv` is available in the original checkout `/Users/wrd/Desktop/codex workspace/CAD/.venv`; invoke its Python from this worktree.
- Run focused new API/scene tests and existing web API/runtime tests. Full suite and 7 regression cases run after integration.
- Actual single and dual job must reach a formal gated result with the same history task ID and correct source-labeled scene; failed job must preserve its real stage.
- Done when no synthetic CAD/progress is needed by frontend and compatibility checks pass.
