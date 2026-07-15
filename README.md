# Parametric Forming-Grinder Guide CAD

This project generates forming-grinder guide CAD from product, preform, and machine parameters.
Finished shape and preform shape are independent: a finished product may be tile-shaped
or bread-shaped, while its preform may use a concentric-R or rectangular-block profile.
The implemented combinations are defined by machine configuration and regression tests.

## Explicit Dual-Spec Input

Machine generation accepts the canonical input fields below.  The pre-grinding
specification owns the passing envelope, tolerances, slot width, and guide base
thickness.  The finished specification owns the finished shape and radius data.

```json
{
  "pre_grinding_spec": "46*12.2(-0.09/-0.11)*2.1(+0.01/-0.01)",
  "finished_spec": "R24.7*12*46*2.1",
  "product_shape_before": "rectangular_block",
  "product_shape_after": "bread_shape",
  "machine_type": "triple_single_down_up",
  "guide_rail_type": "single_guide",
  "wheel_sequence": ["下", "上"],
  "first_wheel_side": "lower",
  "template_coordinate_system": "section_xy_y_up",
  "tolerance": {
    "width_upper_deviation": -0.09,
    "width_lower_deviation": -0.11,
    "thickness_upper_deviation": 0.01,
    "thickness_lower_deviation": -0.01
  }
}
```

`finished_product_spec`, `pre_grinding_shape`, and
`finished_product_shape` remain accepted as compatibility aliases.  New inputs
should use the canonical names above.  `guide_profile_source` is now derived by
the centralized groove decision; if a legacy caller supplies it, the value must
match the decision or generation stops.

```bash
python3 -m src.generate_machine \
  --machine-id triple_single_down_up \
  --input-json examples/dual_spec/example_3.json \
  --output-dir output/dual_spec_examples
```

## Shape Model

- `finished_shape`: finished product shape, such as `tile` or `bread`
- `preform_shape`: forming-grind input shape, such as `concentric_r` or `block`
- `finished_spec`: finished dimensions and target profile
- `preform_spec`: preform dimensions and tolerances

Guide geometry must be selected from the combination of finished shape, preform
shape, and machine configuration. A tile-shaped finished product does not imply
that its preform or guide cavity uses two concentric arcs.

The pure business-layer entry point is
`src.groove_profile.determine_groove_profile()`.  It returns the groove profile,
flat/arc sides, radius source, arc-center side, dimension sources, confidence,
and warnings before any DXF entity is written.

## Tile Finished-Spec Inputs

- `R_outer_finished`: finished outer arc radius in mm
- `R_inner_finished`: finished inner arc radius in mm
- `chord_width`: straight-line distance between the left and right endpoints in mm, with upper/lower preform width tolerance
- `length`: product length in mm, preserved in metadata and reports in this first stage
- `finished_thickness`: finished radial thickness in mm

The forming profile uses `R_form = max(R_outer_finished, R_inner_finished)`.
Wheel and guide design should use `forming_profile`, not `finished_profile`.
The finished thickness is an explicit wall-thickness field from the company
specification; it is not inferred from the difference between the two R values.

General guide-thickness rule:

```text
preform_thickness_mid = preform_thickness + average(thickness_tolerance)
guide_thickness = preform_thickness_mid + process_thickness_clearance
```

For a concentric-R small-tile process without a separate preform-thickness input,
the documented process default may derive `preform_thickness_mid` from finished
thickness. For a block-to-tile process, the explicit block preform thickness and
its tolerances control guide thickness.

Guide defaults:

- chord-width tolerance is required, for example `6.20(-0.02/-0.04)`
- `guide_slot_width = chord_width + average(width_tolerance) + slot_clearance_mid`, rounded half-up to 0.01 mm for machine precision
- `slot_clearance_mid = 0.04` when preform width tolerance range is `<= 0.02 mm`
- `slot_clearance_mid = 0.05` when preform width tolerance range is `> 0.02 mm`
- `guide_slot_width_tolerance = +/-0.01`
- `product_preform_width = chord_width(-0.02/-0.04)`
- `relief_label = 4-r0.5`
- fixed guide template: `outer_width=33.0`, `outer_height=27.0`, `slot_base_height=12.0`, `center_offset=1.5`

## Run Tests

```bash
python3 -m pytest
```

## Local Web Workbench

The `frontend/` workspace provides the local industrial UI for explicit
dual-spec tasks.  It calls `src.web_api` so calculation, validation, and the
release gate remain in the existing Python domain layer; the browser does not
reimplement process formulas.

First-time environment setup:

```bash
python3.11 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
cd frontend && npm ci
```

Python 3.10 or later is required. On macOS, do not use the system-provided
Python 3.9; install Python 3.11 or newer and create the virtual environment
with that interpreter.

Then start both the API and frontend from the repository root with one command:

```bash
./scripts/start_web.sh
```

Before the first start, copy `.env.example` to `.env` and configure the login
accounts and a long random `CAD_SESSION_SECRET`.  Credentials must remain in
the local `.env`, never in source control.  `CAD_ADMIN_USERNAME` can be set to
`sz2026`; set its password in `CAD_ADMIN_PASSWORD`.  Ordinary users are added
through `CAD_OPERATOR_ACCOUNTS_JSON`, for example
`{"operator_1":"a-local-password"}`.
Additional local accounts may be supplied through
`CAD_ADDITIONAL_OPERATOR_ACCOUNTS_JSON`; both variables remain in the ignored
`.env` file and are merged by the authentication service.

Open `http://127.0.0.1:5173`. Press `Ctrl+C` in that terminal to stop the
frontend and any API process started by the script. Generated Web tasks are written under
`output/web_tasks/<task_id>/`. The frontend will show a formal release download
only when the Python report marks `release_allowed` as `true`.

The dashboard and **历史任务** page read these task directories directly. Existing
tasks that predate the history feature are reconstructed from `input.json` and
`report.json`; new tasks also write `task_status.json` so running state and failure
reasons remain visible. The history page supports status/specification filtering,
batch selection, a visible task-detail drawer, validation summaries, previews,
and the same role-based file permissions as the generation result page.
Administrators can delete any completed task. Ordinary users can delete only
tasks created by their authenticated username; legacy tasks without ownership
metadata remain administrator-only. Batch deletion reports skipped running or
unauthorized tasks instead of silently failing. Completed tasks older than
`CAD_TASK_RETENTION_DAYS` (30 days by default) are deleted automatically when
task history is loaded or a new task starts; running tasks are never purged.

The generated preview is a dimensioned guide-rail section only: it does not
contain a side view.  It is available in the result page for visual checking,
but it is not listed as a normal-user download. Ordinary users can download the
validated release DXF and, when conversion succeeds, the AutoCAD 2007/LT 2007
DWG. Administrators can additionally access the
debug DXF, preview PNG, validation report, and dimension-definition-point
audit for maintenance and diagnosis.

After a DXF passes the existing release gate, the Web service uses an installed
AutoCAD Core Console to create a genuine `AC1021` DWG beside it. AutoCAD 2024 for
macOS is auto-detected; other installations can be configured with the absolute
`CAD_AUTOCAD_CORE_CONSOLE` path. DWG conversion does not replace or weaken the
validated DXF gate. If the converter is unavailable, the report records the
reason and the validated DXF remains available.

The Web workbench supports single-guide machines and the synchronized
three-head dual-guide machines (`triple_double_down_up_up` and
`triple_double_up_up_up`). Dual-guide jobs are generated only through
`DualGuideTemplateEngine`; both sections must pass synchronization and dimension
definition-point audits before a formal DXF is exposed.

## Template Asset Delivery

All source DXF templates required by the generator are versioned under
`templates/`. Legacy section-dimension references live in
`templates/legacy_reference/`; generated or ad-hoc DXF files must not be placed
at the repository root because root-level CAD artifacts are ignored by Git.

Before publishing a release to GitHub or deploying to a Mac mini, run the
clean-checkout verifier after committing the changes:

```bash
PYTHON_BIN=python3.11 ./scripts/verify_clean_checkout.sh
```

It exports the committed tree, verifies the required CAD templates, installs
Python and frontend dependencies, builds the frontend, and runs the test suite.
The same checks run in GitHub Actions for every push and pull request.

For explicit dual-spec tasks, the formal DXF filename is fixed as
`成品规格（磨前规格）机台类型.dxf`. Tolerance annotations are deliberately excluded
from the filename, while remaining in the drawing and validation report. To
keep a downloaded file portable on macOS and Windows, specification separators
are displayed as `×` instead of `*`; for example:

```text
R20.15×7×41×1.65（41×7×1.7）双头机（上下）.dxf
```

## Generate Output

Install dependencies first:

```bash
python3 -m pip install -r requirements.txt
```

Then generate machine-specific debug/release DXF, PNG preview, and JSON report:

```bash
python3 -m src.generate_machine --machine-id double_head_up_down --spec "R17.45*R15.8*6.20(-0.02/-0.04)*15.5*1.65"
```

Override relief if needed:

```bash
python3 -m src.generate --spec "R17.45*R15.8*6.20(-0.02/-0.04)*15.5*1.65" --relief "4-0.6" --output-dir output
```

Company specs use this fixed meaning:

```text
R_outer_finished * R_inner_finished * chord_width * length * finished_thickness
```

The generator rebuilds all control points from these values. It does not modify
template CAD entities.

Core API:

```python
from src.geometry import build_tile_section
from src.spec_parser import parse_company_tile_spec

spec = parse_company_tile_spec("R17.45*R15.8*6.20(-0.02/-0.04)*15.5*1.65")
tile_section = build_tile_section(spec)

finished_profile = tile_section.finished_profile
forming_profile = tile_section.forming_profile
guide_spec = tile_section.guide_spec
```

Outputs are written to:

- `output/dxf/`
- `output/preview/`
- `output/reports/`

If geometry validation fails, the command writes an error report and does not write a formal DXF.
