"""Local HTTP adapter for the parametric guide generator.

The UI deliberately talks to this thin layer instead of reproducing process
rules in TypeScript.  Every calculation and release decision remains owned by
the existing Python domain modules.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4
import json
import subprocess
import sys

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .guide_design_input import build_single_guide_profile_from_input
from .machine_config import MachineConfig, load_machine_config


PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_ROOT = PROJECT_ROOT / "templates"
WEB_OUTPUT_ROOT = PROJECT_ROOT / "output" / "web_tasks"


class DesignInput(BaseModel):
    """Canonical explicit dual-spec input passed from the UI."""

    machine_type: str
    guide_rail_type: str
    wheel_sequence: list[str]
    first_wheel_side: str
    template_coordinate_system: str
    finished_spec: str
    pre_grinding_spec: str
    product_shape_after: str
    product_shape_before: str
    tolerance: dict[str, float | None] = Field(default_factory=dict)
    relief: str = "4-1"


class GenerationRequest(BaseModel):
    design: DesignInput


app = FastAPI(title="Forming Grinder Guide CAD API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/machines")
def list_machines() -> list[dict[str, Any]]:
    """Expose template-derived machine metadata without making it editable."""
    machines: list[dict[str, Any]] = []
    for config_path in sorted(TEMPLATE_ROOT.glob("*/config.yaml")):
        machine = load_machine_config(config_path.parent.name)
        machines.append(_machine_payload(machine))
    return machines


@app.post("/api/designs/validate")
def validate_design(design: DesignInput) -> dict[str, Any]:
    """Parse and calculate a design without writing any DXF artifacts."""
    machine = _load_matching_machine(design)
    try:
        _, _, profile, decision = build_single_guide_profile_from_input(
            design.model_dump(), machine
        )
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    guide = profile.guide_spec
    return {
        "machine": _machine_payload(machine),
        "decision": decision.as_dict(),
        "derived": {
            "slot_width": guide.guide_slot_width,
            "slot_width_tolerance": guide.slot_width_tolerance,
            "slot_width_raw": guide.guide_slot_width_raw,
            "guide_thickness": guide.guide_thickness,
            "thickness_clearance_mid": guide.thickness_clearance_mid_value,
            "center_opening": guide.center_opening,
            "relief_label": guide.relief.relief_label,
            "outer_width": guide.outer_width,
            "outer_height": guide.outer_height,
        },
        "release_ready": False,
        "message": "参数解析与计算成功；正式 release 仍需通过完整 DXF 校验。",
    }


@app.post("/api/designs/generate")
def generate_design(request: GenerationRequest) -> dict[str, Any]:
    """Run the existing release-gated generator in an isolated task directory."""
    machine = _load_matching_machine(request.design)
    if machine.guide_sections != 1:
        raise HTTPException(
            status_code=409,
            detail="该机台的双导轨生成流程尚未接入 Web 任务适配层。",
        )

    # Validate before starting a generator subprocess so malformed data never
    # produces an output directory that looks like a legitimate task.
    validate_design(request.design)
    task_id = uuid4().hex[:12]
    task_dir = WEB_OUTPUT_ROOT / task_id
    task_dir.mkdir(parents=True, exist_ok=False)
    input_path = task_dir / "input.json"
    input_path.write_text(
        json.dumps(request.design.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    command = [
        sys.executable,
        "-m",
        "src.generate_machine",
        "--machine-id",
        machine.machine_id,
        "--input-json",
        str(input_path),
        "--output-dir",
        str(task_dir / "artifacts"),
    ]
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    result = {
        "task_id": task_id,
        "task_directory": str(task_dir),
        "ok": completed.returncode == 0,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    if completed.returncode != 0:
        return result

    report_path = next((task_dir / "artifacts").glob("**/*_report.json"), None)
    if report_path is None:
        return {**result, "ok": False, "stderr": "生成未写出 report.json。"}
    report = json.loads(report_path.read_text(encoding="utf-8"))
    return {
        **result,
        "release_allowed": bool(report.get("release_allowed")),
        "report": report,
        "files": _task_file_payload(task_id, task_dir, report),
    }


@app.get("/api/tasks/{task_id}/files/{relative_path:path}")
def read_task_file(task_id: str, relative_path: str) -> FileResponse:
    """Serve only files generated inside one Web task directory."""
    if not task_id.isalnum() or len(task_id) != 12:
        raise HTTPException(status_code=404, detail="任务不存在。")
    task_dir = (WEB_OUTPUT_ROOT / task_id).resolve()
    requested = (task_dir / relative_path).resolve()
    if not requested.is_relative_to(task_dir) or not requested.is_file():
        raise HTTPException(status_code=404, detail="生成文件不存在。")
    return FileResponse(requested, filename=requested.name)


def _load_matching_machine(design: DesignInput) -> MachineConfig:
    try:
        machine = load_machine_config(design.machine_type)
    except (FileNotFoundError, KeyError, ValueError) as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    if machine.guide_type != design.guide_rail_type:
        raise HTTPException(status_code=422, detail="导轨类型与所选机台配置不一致。")
    if list(machine.wheel_positions) != design.wheel_sequence:
        raise HTTPException(status_code=422, detail="砂轮顺序与所选机台配置不一致。")
    return machine


def _machine_payload(machine: MachineConfig) -> dict[str, Any]:
    return {
        "id": machine.machine_id,
        "name": machine.machine_name,
        "guide_type": machine.guide_type,
        "guide_length": machine.guide_length,
        "guide_sections": machine.guide_sections,
        "wheel_positions": list(machine.wheel_positions),
        "section_outer_width": machine.section_outer_width,
        "section_center_opening": machine.section_center_opening,
        "section_slot_base_height": machine.section_slot_base_height,
        "template_coordinate_system": machine.template_coordinate_system,
        "supported_by_web_generation": machine.guide_sections == 1,
    }


def _task_file_payload(
    task_id: str,
    task_dir: Path,
    report: dict[str, Any],
) -> dict[str, dict[str, str]]:
    """Turn report paths into task-scoped, browser-safe download URLs."""
    files: dict[str, dict[str, str]] = {}
    path_keys = {
        "debug_dxf": "debug DXF",
        "release_dxf": "release DXF",
        "preview_png": "图纸预览",
    }
    for report_key, label in path_keys.items():
        raw_path = report.get("paths", {}).get(report_key)
        if not raw_path:
            continue
        candidate = Path(str(raw_path)).resolve()
        if candidate.is_file() and candidate.is_relative_to(task_dir.resolve()):
            relative_path = candidate.relative_to(task_dir).as_posix()
            files[report_key] = {
                "label": label,
                "name": candidate.name,
                "url": f"/api/tasks/{task_id}/files/{relative_path}",
            }
    for candidate in task_dir.glob("**/*dimension_definition_point_audit.json"):
        relative_path = candidate.relative_to(task_dir).as_posix()
        files["dimension_audit"] = {
            "label": "尺寸定义点审计",
            "name": candidate.name,
            "url": f"/api/tasks/{task_id}/files/{relative_path}",
        }
    report_path = next(iter(task_dir.glob("**/*_report.json")), None)
    if report_path is not None:
        relative_path = report_path.relative_to(task_dir).as_posix()
        files["report_json"] = {
            "label": "校验报告",
            "name": report_path.name,
            "url": f"/api/tasks/{task_id}/files/{relative_path}",
        }
    return files
