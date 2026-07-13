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

Start the API from the repository root:

```bash
python3 -m pip install -r requirements.txt
python3 -m uvicorn src.web_api:app --reload
```

Then start the frontend in a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. Generated Web tasks are written under
`output/web_tasks/<task_id>/`. The frontend will show a formal release download
only when the Python report marks `release_allowed` as `true`.

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
