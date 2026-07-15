"""Local HTTP adapter for the parametric guide generator.

The UI deliberately talks to this thin layer instead of reproducing process
rules in TypeScript.  Every calculation and release decision remains owned by
the existing Python domain modules.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4
import json
import subprocess
import sys

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .block_geometry import BlockGuideSection
from .auth import (
    SESSION_COOKIE_NAME,
    SESSION_TTL_SECONDS,
    AuthenticatedUser,
    authenticate,
    create_session_token,
    require_user,
    session_cookie_secure,
)
from .dual_guide_engine import DualGuideTemplateEngine
from .dual_guide_input import build_dual_guide_profile_from_input
from .geometry import TileSection
from .groove_profile import determine_groove_profile, normalize_shape
from .global_rules import DEFAULT_WHEEL_RADIUS
from .guide_design_input import build_single_guide_profile_from_input, machine_template_rules
from .machine_config import MachineConfig, load_machine_config
from .output_naming import build_machine_output_stem
from .preview import write_block_png_preview, write_png_preview
from .spec_parser import parse_company_bread_spec, parse_company_tile_spec


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
    single_side_or_high_requirement: bool = False
    high_symmetry_requirement: bool = False
    large_tile_clearance: bool = False
    wheel_radius: float = Field(default=DEFAULT_WHEEL_RADIUS, gt=0.0)


class GenerationRequest(BaseModel):
    design: DesignInput


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=512)


app = FastAPI(title="Forming Grinder Guide CAD API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/auth/login")
def login(credentials: LoginRequest, response: Response) -> dict[str, str]:
    user = authenticate(credentials.username, credentials.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误。")
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=create_session_token(user),
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=session_cookie_secure(),
        samesite="strict",
        path="/",
    )
    return {"username": user.username, "role": user.role}


@app.post("/api/auth/logout", dependencies=[Depends(require_user)])
def logout(response: Response) -> dict[str, str]:
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return {"status": "ok"}


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
    if not user.is_administrator and not _is_operator_visible_file(task_dir, requested):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="普通用户只能下载正式 release DXF。")
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

    task_id = uuid4().hex[:12]
    task_dir = WEB_OUTPUT_ROOT / task_id
    task_dir.mkdir(parents=True, exist_ok=False)
    (task_dir / "input.json").write_text(
        json.dumps(design.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
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
        return {
            "task_id": task_id,
            "task_directory": str(task_dir),
            "ok": False,
            "stdout": "",
            "stderr": str(error),
        }

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
    report_path = result["report_json"]
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "task_id": task_id,
        "task_directory": str(task_dir),
        "ok": bool(report.get("release_allowed")),
        "stdout": "",
        "stderr": "" if report.get("release_allowed") else "双导轨 release 校验未通过。",
        "release_allowed": bool(report.get("release_allowed")),
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


def _task_file_payload(
    task_id: str,
    task_dir: Path,
    report: dict[str, Any],
    user: AuthenticatedUser | None = None,
) -> dict[str, dict[str, str]]:
    """Expose only the artifacts the authenticated role is allowed to download."""
    files: dict[str, dict[str, str]] = {}
    path_keys = {"release_dxf": "release DXF"}
    if user is None or user.is_administrator:
        path_keys = {
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
    if user is not None and not user.is_administrator:
        return files
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


def _is_operator_visible_file(task_dir: Path, requested: Path) -> bool:
    """Operators may inspect the generated section but download only release DXF."""
    report_path = next(iter(task_dir.glob("**/*_report.json")), None)
    if report_path is None:
        return False
    try:
        paths = json.loads(report_path.read_text(encoding="utf-8")).get("paths", {})
        release_path = Path(str(paths["release_dxf"])).resolve()
        preview_path = Path(str(paths["preview_png"])).resolve()
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return False
    return requested == release_path or requested == preview_path
