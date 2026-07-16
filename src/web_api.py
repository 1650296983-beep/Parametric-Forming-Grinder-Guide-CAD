"""Local HTTP adapter for the parametric guide generator.

The UI deliberately talks to this thin layer instead of reproducing process
rules in TypeScript.  Every calculation and release decision remains owned by
the existing Python domain modules.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4
import json
import os
import subprocess
import sys

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .block_geometry import BlockGuideSection
from .auth import (
    AuthenticatedUser,
    require_user,
)
from desktop.runtime_paths import (
    get_runtime_paths,
    is_desktop_mode,
    read_settings,
    resource_root,
    write_settings,
)
from .dual_guide_engine import DualGuideTemplateEngine
from .dual_guide_input import build_dual_guide_profile_from_input
from .dwg_converter import (
    AUTOCAD_2007_DWG_VERSION,
    AUTOCAD_2007_FORMAT_LABEL,
    DwgConversionError,
    autocad_detection_payload,
    convert_release_dxf_to_autocad_2007_dwg,
    dwg_conversion_available,
)
from .geometry import TileSection
from .groove_profile import determine_groove_profile, normalize_shape
from .global_rules import DEFAULT_WHEEL_RADIUS
from .guide_design_input import build_single_guide_profile_from_input, machine_template_rules
from .machine_config import MachineConfig, load_machine_config
from .output_naming import build_machine_output_stem
from .preview import write_block_png_preview, write_png_preview
from .spec_parser import parse_company_bread_spec, parse_company_tile_spec
from .web_task_repository import StoredWebTask, WebTaskRepository


PROJECT_ROOT = resource_root()
TEMPLATE_ROOT = PROJECT_ROOT / "templates"
WEB_OUTPUT_ROOT = get_runtime_paths().tasks


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
    single_side_or_high_requirement: bool = False
    high_symmetry_requirement: bool = False
    large_tile_clearance: bool = False
    wheel_radius: float = Field(default=DEFAULT_WHEEL_RADIUS, gt=0.0)


class GenerationRequest(BaseModel):
    design: DesignInput


class BulkDeleteRequest(BaseModel):
    task_ids: list[str] = Field(min_length=1, max_length=500)


class DesktopSettingsUpdate(BaseModel):
    autocad_core_console: str | None = Field(default=None, max_length=4096)


app = FastAPI(title="Forming Grinder Guide CAD API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://tauri.localhost",
        "tauri://localhost",
        "https://tauri.localhost",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/desktop/shutdown", include_in_schema=False)
def desktop_shutdown() -> dict[str, str]:
    callback = getattr(app.state, "request_desktop_shutdown", None)
    if callback is None:
        raise HTTPException(status_code=409, detail="当前不是受管桌面 sidecar。")
    callback()
    return {"status": "stopping"}


@app.get("/api/auth/me")
def current_user(user: AuthenticatedUser = Depends(require_user)) -> dict[str, str]:
    return {"username": user.username, "role": user.role}


@app.get("/api/machines", dependencies=[Depends(require_user)])
def list_machines() -> list[dict[str, Any]]:
    """Expose template-derived machine metadata without making it editable."""
    machines: list[dict[str, Any]] = []
    for config_path in sorted(TEMPLATE_ROOT.glob("*/config.yaml")):
        machine = load_machine_config(config_path.parent.name)
        machines.append(_machine_payload(machine))
    return machines


@app.get("/api/settings", dependencies=[Depends(require_user)])
def get_desktop_settings() -> dict[str, Any]:
    settings = read_settings()
    return {
        "autocad_core_console": settings.get("autocad_core_console"),
        "autocad": autocad_detection_payload(),
        "app_data_root": str(get_runtime_paths().app_data_root),
    }


@app.put("/api/settings", dependencies=[Depends(require_user)])
def update_desktop_settings(update: DesktopSettingsUpdate) -> dict[str, Any]:
    value = update.autocad_core_console.strip() if update.autocad_core_console else None
    if value:
        candidate = Path(value).expanduser()
        expected_name = "AcCoreConsole.exe" if sys.platform == "win32" else "AcCoreConsole"
        if not candidate.is_file() or candidate.name.lower() != expected_name.lower():
            raise HTTPException(status_code=422, detail="请选择有效的 AcCoreConsole 可执行文件。")
    settings = read_settings()
    if value:
        settings["autocad_core_console"] = value
    else:
        settings.pop("autocad_core_console", None)
    write_settings(settings)
    return get_desktop_settings()


@app.post("/api/designs/validate", dependencies=[Depends(require_user)])
def validate_design(design: DesignInput) -> dict[str, Any]:
    """Parse and calculate a design without writing any DXF artifacts."""
    machine = _load_matching_machine(design)
    try:
        _, _, profile, decision = _build_profile_for_design(design, machine)
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    guide = profile.guide_spec
    return {
        "machine": _machine_payload(machine),
        "decision": decision,
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
def generate_design_endpoint(
    request: GenerationRequest,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    return generate_design(request, user)


@app.get("/api/tasks")
def list_tasks(
    limit: int = 100,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    """List persisted Web tasks and report-derived dashboard metrics."""
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=422, detail="历史任务数量必须在 1 到 500 之间。")
    retention_days = _task_retention_days()
    repository = WebTaskRepository(WEB_OUTPUT_ROOT)
    if retention_days > 0:
        repository.delete_expired(retention_days)
    records = repository.list()
    return {
        "items": [_task_summary_payload(record, user) for record in records[:limit]],
        "metrics": _task_metrics(records),
        "retention_days": retention_days,
    }


@app.get("/api/tasks/{task_id}")
def get_task(
    task_id: str,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    """Return an input snapshot, report summary, preview, and authorized files."""
    record = WebTaskRepository(WEB_OUTPUT_ROOT).get(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail="任务不存在。")
    summary = _task_summary_payload(record, user)
    report = record.report or {}
    return {
        **summary,
        "input": record.design,
        "audit": {
            "release_allowed": bool(report.get("release_allowed")),
            "inspection_passed": bool(report.get("inspection", {}).get("release_allowed")),
            "dimension_points_passed": bool(
                report.get("dimension_definition_point_audit", {}).get("release_allowed")
            ),
            "workflow": report.get("workflow", []),
        },
    }


@app.delete("/api/tasks/{task_id}")
def delete_task(
    task_id: str,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, str]:
    """Delete one completed local task."""
    repository = WebTaskRepository(WEB_OUTPUT_ROOT)
    record = repository.get(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail="任务不存在。")
    if record.status == "running":
        raise HTTPException(status_code=409, detail="执行中的任务不能删除。")
    if not repository.delete(task_id):
        raise HTTPException(status_code=404, detail="任务不存在。")
    return {"task_id": task_id, "status": "deleted"}


@app.post("/api/tasks/bulk-delete")
def bulk_delete_tasks(
    request: BulkDeleteRequest,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    """Delete completed local tasks and report every skipped item."""
    repository = WebTaskRepository(WEB_OUTPUT_ROOT)
    deleted: list[str] = []
    skipped: list[dict[str, str]] = []
    for task_id in dict.fromkeys(request.task_ids):
        record = repository.get(task_id)
        if record is None:
            skipped.append({"task_id": task_id, "reason": "任务不存在。"})
            continue
        if record.status == "running":
            skipped.append({"task_id": task_id, "reason": "执行中的任务不能删除。"})
            continue
        if repository.delete(task_id):
            deleted.append(task_id)
        else:
            skipped.append({"task_id": task_id, "reason": "任务删除时已不存在。"})
    return {"deleted": deleted, "skipped": skipped}


def generate_design(
    request: GenerationRequest,
    user: AuthenticatedUser | None = None,
) -> dict[str, Any]:
    """Run the existing release-gated generator in an isolated task directory."""
    machine = _load_matching_machine(request.design)
    if machine.guide_sections == 2:
        return _generate_dual_guide_design(request.design, machine, user=user)

    # Validate before starting a generator subprocess so malformed data never
    # produces an output directory that looks like a legitimate task.
    validate_design(request.design)
    task_id, task_dir, input_path = _initialize_task(request.design, user)
    command = [sys.executable]
    if getattr(sys, "frozen", False):
        command.append("generate-machine")
    else:
        command.extend(("-m", "src.generate_machine"))
    command.extend([
        "--machine-id",
        machine.machine_id,
        "--input-json",
        str(input_path),
        "--output-dir",
        str(task_dir / "artifacts"),
    ])
    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        message = f"生成进程启动失败：{error}"
        WebTaskRepository(WEB_OUTPUT_ROOT).finish(task_dir, status="failed", error=message)
        return {
            "task_id": task_id,
            "task_directory": str(task_dir),
            "ok": False,
            "stdout": "",
            "stderr": message,
        }
    result = {
        "task_id": task_id,
        "task_directory": str(task_dir),
        "ok": completed.returncode == 0,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    if completed.returncode != 0:
        WebTaskRepository(WEB_OUTPUT_ROOT).finish(
            task_dir,
            status="failed",
            error=completed.stderr or "生成进程未成功完成。",
        )
        return result

    report_path = next((task_dir / "artifacts").glob("**/*_report.json"), None)
    if report_path is None:
        message = "生成未写出 report.json。"
        WebTaskRepository(WEB_OUTPUT_ROOT).finish(task_dir, status="failed", error=message)
        return {**result, "ok": False, "stderr": message}
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        message = f"report.json 读取失败：{error}"
        WebTaskRepository(WEB_OUTPUT_ROOT).finish(task_dir, status="failed", error=message)
        return {**result, "ok": False, "stderr": message}
    release_allowed = bool(report.get("release_allowed"))
    if release_allowed:
        _add_autocad_2007_dwg_export(report)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    WebTaskRepository(WEB_OUTPUT_ROOT).finish(
        task_dir,
        status="passed" if release_allowed else "failed",
        error=None if release_allowed else "完整 DXF 校验未通过，release.dxf 未输出。",
    )
    return {
        **result,
        "release_allowed": release_allowed,
        "report": report,
        "preview": _task_preview_payload(task_id, task_dir, report),
        "files": _task_file_payload(task_id, task_dir, report, user=user),
    }


@app.get("/api/tasks/{task_id}/files/{relative_path:path}")
def read_task_file(
    task_id: str,
    relative_path: str,
    user: AuthenticatedUser = Depends(require_user),
) -> FileResponse:
    """Serve only files generated inside one Web task directory."""
    if not task_id.isalnum() or len(task_id) != 12:
        raise HTTPException(status_code=404, detail="任务不存在。")
    task_dir = (WEB_OUTPUT_ROOT / task_id).resolve()
    requested = (task_dir / relative_path).resolve()
    if not requested.is_relative_to(task_dir) or not requested.is_file():
        raise HTTPException(status_code=404, detail="生成文件不存在。")
    return FileResponse(
        requested,
        filename=requested.name,
        content_disposition_type="inline" if requested.suffix.lower() == ".png" else "attachment",
    )


def _load_matching_machine(design: DesignInput) -> MachineConfig:
    try:
        machine = load_machine_config(design.machine_type)
    except (FileNotFoundError, KeyError, ValueError) as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    if machine.guide_type != design.guide_rail_type:
        raise HTTPException(status_code=422, detail="导轨类型与所选机台配置不一致。")
    if list(machine.wheel_positions) != design.wheel_sequence:
        raise HTTPException(status_code=422, detail="砂轮顺序与所选机台配置不一致。")
    expected_first_side = _first_wheel_side(machine)
    if design.first_wheel_side != expected_first_side:
        raise HTTPException(
            status_code=422,
            detail=f"第一砂轮方向与机台配置不一致，应为 {expected_first_side}。",
        )
    if design.template_coordinate_system != machine.template_coordinate_system:
        raise HTTPException(status_code=422, detail="模板坐标系与所选机台配置不一致。")
    return replace(machine, wheel_radius=design.wheel_radius)


def _build_profile_for_design(
    design: DesignInput,
    machine: MachineConfig,
) -> tuple[Any, Any, TileSection | BlockGuideSection, dict[str, Any]]:
    if machine.guide_sections == 1:
        finished, pre_grinding, profile, decision = build_single_guide_profile_from_input(
            design.model_dump(), machine
        )
        return finished, pre_grinding, profile, decision.as_dict()
    if machine.guide_sections == 2:
        return _build_dual_profile_for_web_design(design, machine)
    raise ValueError(f"Web generation does not support guide_sections={machine.guide_sections}.")


def _build_dual_profile_for_web_design(
    design: DesignInput,
    machine: MachineConfig,
) -> tuple[Any, Any, TileSection | BlockGuideSection, dict[str, Any]]:
    """Translate Web's canonical input into the existing dual-guide contract."""
    if design.tolerance:
        raise ValueError("双导轨任务不接受独立 tolerance 字段；请仅在磨前规格中填写公差。")
    finished_shape = normalize_shape(design.product_shape_after)
    pre_grinding_shape = normalize_shape(design.product_shape_before)
    shape_map = {"bread_shape": "bread", "tile_shape": "tile"}
    preform_map = {"rectangular_block": "block", "same_r_tile": "same_r_tile"}
    if finished_shape not in shape_map or pre_grinding_shape not in preform_map:
        raise ValueError("双导轨仅支持馒头/瓦型成品与方块/同 R 瓦型磨前形态。")
    finished_radii = _finished_radii_for_web_design(design.finished_spec, finished_shape)
    groove = determine_groove_profile(
        product_shape_before=pre_grinding_shape,
        product_shape_after=finished_shape,
        finished_radius_count=len(finished_radii),
        machine_type=machine.machine_id,
        guide_rail_type=machine.guide_type,
        wheel_sequence=machine.wheel_positions,
        template_rules=machine_template_rules(machine),
        finished_radii=finished_radii,
        first_wheel_side=design.first_wheel_side,
    )
    if groove.groove_profile == "manual_review" or groove.guide_profile_source is None:
        raise ValueError("; ".join(groove.warnings) or "当前双导轨输入需要人工确认。")
    dual_input = {
        "finished_product_spec": design.finished_spec,
        "pre_grinding_spec": design.pre_grinding_spec,
        "finished_product_shape": shape_map[finished_shape],
        "pre_grinding_shape": preform_map[pre_grinding_shape],
        "guide_profile_source": groove.guide_profile_source,
        "relief": design.relief,
        "single_side_or_high_requirement": design.single_side_or_high_requirement,
        "high_symmetry_requirement": design.high_symmetry_requirement,
        "large_tile_clearance": design.large_tile_clearance,
        "wheel_radius": design.wheel_radius,
    }
    finished, pre_grinding, profile, dual_decision = build_dual_guide_profile_from_input(
        dual_input,
        machine,
    )
    input_rule = {
        **dual_decision.as_dict(),
        **groove.as_dict(),
        "finished_spec": design.finished_spec,
        "product_shape_before": pre_grinding_shape,
        "product_shape_after": finished_shape,
        "machine_type": machine.machine_id,
        "guide_rail_type": machine.guide_type,
        "wheel_sequence": list(machine.wheel_positions),
        "first_wheel_side": design.first_wheel_side,
        "template_coordinate_system": machine.template_coordinate_system,
        "wheel_radius": machine.wheel_radius,
        "input_rule_valid": True,
        "input_mode": "web_explicit_input",
    }
    return finished, pre_grinding, profile, input_rule


def _finished_radii_for_web_design(finished_spec: str, finished_shape: str) -> tuple[float, ...]:
    if finished_shape == "bread_shape":
        return (parse_company_bread_spec(finished_spec).R_outer_finished,)
    tile_spec = parse_company_tile_spec(finished_spec, require_chord_tolerance=False)
    return (tile_spec.R_outer_finished, tile_spec.R_inner_finished)


def _generate_dual_guide_design(
    design: DesignInput,
    machine: MachineConfig,
    user: AuthenticatedUser | None = None,
) -> dict[str, Any]:
    """Generate dual guides through DualGuideTemplateEngine and preserve its gate."""
    try:
        _, pre_grinding, profile, input_rule = _build_profile_for_design(design, machine)
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    task_id, task_dir, _ = _initialize_task(design, user)
    artifact_stem = build_machine_output_stem(
        design.finished_spec,
        design.pre_grinding_spec,
        machine.machine_name,
    )
    try:
        result = DualGuideTemplateEngine(machine).write_debug_release_and_report(
            profile,
            pre_grinding,
            task_dir / "artifacts",
            input_rule=input_rule,
            artifact_stem=artifact_stem,
        )
    except (OSError, TypeError, ValueError) as error:
        WebTaskRepository(WEB_OUTPUT_ROOT).finish(task_dir, status="failed", error=str(error))
        return {
            "task_id": task_id,
            "task_directory": str(task_dir),
            "ok": False,
            "stdout": "",
            "stderr": str(error),
        }

    try:
        preview_path = task_dir / "artifacts" / f"{artifact_stem}.png"
        if isinstance(profile, TileSection):
            write_png_preview(
                profile,
                preview_path,
                side_layout=machine.side_layout,
                machine_name=f"{machine.machine_id} {machine.guide_length:.0f}mm",
            )
        else:
            write_block_png_preview(profile, machine, preview_path)
        report = result["report"]
        report["paths"] = {
            "debug_dxf": str(result["debug_dxf"]),
            "release_dxf": str(result["release_dxf"]),
            "preview_png": str(preview_path),
        }
        if bool(report.get("release_allowed")):
            _add_autocad_2007_dwg_export(report)
        report_path = result["report_json"]
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    except (OSError, TypeError, ValueError) as error:
        message = f"任务输出整理失败：{error}"
        WebTaskRepository(WEB_OUTPUT_ROOT).finish(task_dir, status="failed", error=message)
        return {
            "task_id": task_id,
            "task_directory": str(task_dir),
            "ok": False,
            "stdout": "",
            "stderr": message,
        }
    release_allowed = bool(report.get("release_allowed"))
    WebTaskRepository(WEB_OUTPUT_ROOT).finish(
        task_dir,
        status="passed" if release_allowed else "failed",
        error=None if release_allowed else "双导轨 release 校验未通过。",
    )
    return {
        "task_id": task_id,
        "task_directory": str(task_dir),
        "ok": release_allowed,
        "stdout": "",
        "stderr": "" if report.get("release_allowed") else "双导轨 release 校验未通过。",
        "release_allowed": release_allowed,
        "report": report,
        "preview": _task_preview_payload(task_id, task_dir, report),
        "files": _task_file_payload(task_id, task_dir, report, user=user),
    }


def _first_wheel_side(machine: MachineConfig) -> str:
    try:
        return {"上": "upper", "下": "lower", "左": "left", "右": "right"}[machine.wheel_positions[0]]
    except (IndexError, KeyError) as error:
        raise HTTPException(status_code=500, detail="机台配置的首砂轮方向无效。") from error


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
        "wheel_radius": machine.wheel_radius,
        "template_coordinate_system": machine.template_coordinate_system,
        "supported_by_web_generation": machine.guide_sections in {1, 2},
    }


def _initialize_task(
    design: DesignInput,
    user: AuthenticatedUser | None,
) -> tuple[str, Path, Path]:
    retention_days = _task_retention_days()
    if retention_days > 0:
        WebTaskRepository(WEB_OUTPUT_ROOT).delete_expired(retention_days)
    task_id = uuid4().hex[:12]
    task_dir = WEB_OUTPUT_ROOT / task_id
    task_dir.mkdir(parents=True, exist_ok=False)
    input_path = task_dir / "input.json"
    input_path.write_text(
        json.dumps(design.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    WebTaskRepository(WEB_OUTPUT_ROOT).initialize(
        task_dir,
        task_id=task_id,
        created_by=user.username if user is not None else None,
    )
    return task_id, task_dir, input_path


def _task_summary_payload(
    record: StoredWebTask,
    user: AuthenticatedUser,
) -> dict[str, Any]:
    design = record.design
    report = record.report or {}
    machine_data = report.get("machine", {})
    machine_id = str(design.get("machine_type", machine_data.get("machine_id", "")))
    machine_name = machine_data.get("machine_name") or _machine_name(machine_id)
    release_allowed = bool(report.get("release_allowed"))
    return {
        "task_id": record.task_id,
        "task_name": str(design.get("finished_spec", record.task_id)),
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "created_by": record.created_by,
        "can_delete": record.status != "running",
        "status": record.status,
        "error": record.error,
        "machine_id": machine_id,
        "machine_name": machine_name,
        "finished_spec": str(design.get("finished_spec", "")),
        "pre_grinding_spec": str(design.get("pre_grinding_spec", "")),
        "finished_shape": str(design.get("product_shape_after", "")),
        "pre_grinding_shape": str(design.get("product_shape_before", "")),
        "release_allowed": release_allowed,
        "derived": _task_derived_payload(report),
        "preview": _task_preview_payload(record.task_id, record.task_dir, report),
        "files": _task_file_payload(record.task_id, record.task_dir, report, user=user),
    }


def _task_derived_payload(report: dict[str, Any]) -> dict[str, Any]:
    process_parameters = report.get("process_parameters", {})
    shared_parameters = report.get("shared_parameters", {})
    input_rule = report.get("input_rule", {})
    return {
        "slot_width": process_parameters.get("slot_width", {}).get(
            "slot_width", shared_parameters.get("slot_width")
        ),
        "guide_thickness": process_parameters.get("guide_thickness", {}).get(
            "result", shared_parameters.get("guide_thickness")
        ),
        "groove_profile": input_rule.get("groove_profile")
        or report.get("section_profile_type"),
    }


def _machine_name(machine_id: str) -> str:
    try:
        return load_machine_config(machine_id).machine_name
    except (FileNotFoundError, KeyError, ValueError):
        return machine_id or "未知机台"


def _task_metrics(records: list[StoredWebTask]) -> dict[str, int]:
    today = datetime.now().astimezone().date()
    return {
        "total": len(records),
        "today": sum(
            1
            for record in records
            if datetime.fromisoformat(record.created_at.replace("Z", "+00:00")).astimezone().date()
            == today
        ),
        "passed": sum(record.status == "passed" for record in records),
        "failed": sum(record.status == "failed" for record in records),
        "running": sum(record.status == "running" for record in records),
    }


def _task_file_payload(
    task_id: str,
    task_dir: Path,
    report: dict[str, Any],
    user: AuthenticatedUser | None = None,
) -> dict[str, dict[str, str]]:
    """Expose only generated artifacts contained by the selected task."""
    files: dict[str, dict[str, str]] = {}
    path_keys = {
        "release_dwg": "AutoCAD 2007 DWG",
        "debug_dxf": "debug DXF",
        "release_dxf": "release DXF",
        "preview_png": "截面预览图",
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


def _task_preview_payload(
    task_id: str,
    task_dir: Path,
    report: dict[str, Any],
) -> dict[str, str] | None:
    raw_path = report.get("paths", {}).get("preview_png")
    if not raw_path:
        return None
    preview_path = Path(str(raw_path)).resolve()
    if not preview_path.is_file() or not preview_path.is_relative_to(task_dir.resolve()):
        return None
    return {
        "label": "导轨截面预览",
        "name": preview_path.name,
        "url": f"/api/tasks/{task_id}/files/{preview_path.relative_to(task_dir).as_posix()}",
    }


def _task_retention_days() -> int:
    raw_value = os.getenv("CAD_TASK_RETENTION_DAYS", "0" if is_desktop_mode() else "30")
    try:
        retention_days = int(raw_value)
    except ValueError as error:
        raise HTTPException(status_code=503, detail="CAD_TASK_RETENTION_DAYS 必须是整数。") from error
    if not 0 <= retention_days <= 3650:
        raise HTTPException(status_code=503, detail="CAD_TASK_RETENTION_DAYS 必须在 0 到 3650 之间；0 表示长期保留。")
    return retention_days


def _add_autocad_2007_dwg_export(report: dict[str, Any]) -> None:
    """Add a verified AC1021 DWG without changing the DXF release gate."""
    export = {
        "format": AUTOCAD_2007_FORMAT_LABEL,
        "dwg_version": AUTOCAD_2007_DWG_VERSION,
        "generated": False,
        "converter_available": dwg_conversion_available(),
        "error": None,
    }
    report["dwg_export"] = export
    if not export["converter_available"]:
        export["error"] = "未安装或未配置 AutoCAD Core Console；保留通过校验的 release DXF。"
        return
    raw_release_path = report.get("paths", {}).get("release_dxf")
    if not raw_release_path:
        export["error"] = "report.json 未包含 release_dxf 路径。"
        return
    try:
        dwg_path = convert_release_dxf_to_autocad_2007_dwg(
            Path(str(raw_release_path)),
            release_allowed=bool(report.get("release_allowed")),
        )
    except DwgConversionError as error:
        export["error"] = str(error)
        return
    report.setdefault("paths", {})["release_dwg"] = str(dwg_path)
    export["generated"] = True
