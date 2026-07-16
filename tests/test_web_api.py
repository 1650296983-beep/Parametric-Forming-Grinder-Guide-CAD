from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

from fastapi import HTTPException
import pytest

import src.web_api as web_api
from src.auth import AuthenticatedUser, LOCAL_ADMIN, require_user
from src.web_api import (
    BulkDeleteRequest,
    DesignInput,
    GenerationRequest,
    _task_file_payload,
    bulk_delete_tasks,
    delete_task,
    generate_design,
    get_task,
    list_machines,
    list_tasks,
    validate_design,
)
from src.web_task_repository import WebTaskRepository


def _call_asgi(
    method: str,
    path: str,
    *,
    body: bytes = b"",
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    """Exercise FastAPI routes without adding an HTTP client test dependency."""
    response_messages: list[dict] = []
    request_consumed = False
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [(key.lower().encode(), value.encode()) for key, value in (headers or {}).items()],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }

    async def receive() -> dict:
        nonlocal request_consumed
        if not request_consumed:
            request_consumed = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        response_messages.append(message)

    asyncio.run(web_api.app(scope, receive, send))
    start = next(message for message in response_messages if message["type"] == "http.response.start")
    response_body = b"".join(
        message.get("body", b"")
        for message in response_messages
        if message["type"] == "http.response.body"
    )
    response_headers = {key.decode().lower(): value.decode() for key, value in start["headers"]}
    return start["status"], response_headers, response_body


def _triple_single_block_request() -> DesignInput:
    return DesignInput(
        machine_type="triple_single_down_up",
        guide_rail_type="single_guide",
        wheel_sequence=["下", "上"],
        first_wheel_side="lower",
        template_coordinate_system="section_xy_y_up",
        finished_spec="R9.6*8.6*42.6*2.1",
        pre_grinding_spec="42.6*8.6(-0.07/-0.09)*2.1(+0.01/-0.01)",
        product_shape_after="bread_shape",
        product_shape_before="rectangular_block",
        tolerance={
            "width_upper_deviation": -0.07,
            "width_lower_deviation": -0.09,
            "thickness_upper_deviation": 0.01,
            "thickness_lower_deviation": -0.01,
        },
    )


def _triple_double_tile_request() -> DesignInput:
    return DesignInput(
        machine_type="triple_double_down_up_up",
        guide_rail_type="double_guide",
        wheel_sequence=["下", "上", "上"],
        first_wheel_side="lower",
        template_coordinate_system="section_xy_y_up",
        finished_spec="R30*R28*17.4*23.5*3.95",
        pre_grinding_spec="23.5*17.4(+0/-0.02)*3.95(+0.02/-0.02)",
        product_shape_after="tile_shape",
        product_shape_before="rectangular_block",
    )


def test_web_api_lists_template_derived_machines() -> None:
    machines = list_machines()

    triple_single = next(machine for machine in machines if machine["id"] == "triple_single_down_up")
    assert triple_single["guide_length"] == 379.0
    assert triple_single["wheel_positions"] == ["下", "上"]


def test_web_api_calculates_from_existing_dual_spec_rules() -> None:
    result = validate_design(_triple_single_block_request())

    assert result["decision"]["groove_profile"] == "rectangular_groove"
    assert result["derived"]["slot_width"] == 8.56
    assert result["derived"]["guide_thickness"] == 2.22
    assert result["release_ready"] is False


def test_web_api_calculates_dual_guide_with_centralized_profile_rule() -> None:
    result = validate_design(_triple_double_tile_request())

    assert result["machine"]["supported_by_web_generation"] is True
    assert result["decision"]["groove_profile"] == "flat_arc_groove"
    assert result["decision"]["guide_profile_source"] == "finished_product_big_r_with_pre_grinding_block"
    assert result["derived"]["slot_width"] == 17.43


def test_web_api_generates_release_gated_dual_guide_artifacts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(web_api, "WEB_OUTPUT_ROOT", tmp_path)
    monkeypatch.setattr(web_api, "dwg_conversion_available", lambda: False)

    result = generate_design(GenerationRequest(design=_triple_double_tile_request()))

    assert result["ok"] is True
    assert result["release_allowed"] is True
    assert result["report"]["checks"]["synchronized_parameters"] is True
    assert result["report"]["dimension_definition_point_audit"]["release_allowed"] is True
    assert result["files"]["release_dxf"]["name"] == (
        "R30×R28×17.4×23.5×3.95（23.5×17.4×3.95）三头机双导轨（下上上）.dxf"
    )
    assert Path(result["report"]["paths"]["release_dxf"]).is_file()
    assert Path(result["report"]["paths"]["preview_png"]).is_file()
    task_status = json.loads((tmp_path / result["task_id"] / "task_status.json").read_text(encoding="utf-8"))
    assert task_status["status"] == "passed"


def test_task_history_reconstructs_legacy_tasks_and_exposes_details(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(web_api, "WEB_OUTPUT_ROOT", tmp_path)
    user = AuthenticatedUser(username="admin", role="administrator")
    passed_dir = tmp_path / "abc123def456"
    failed_dir = tmp_path / "def456abc123"
    passed_artifacts = passed_dir / "artifacts"
    passed_artifacts.mkdir(parents=True)
    failed_dir.mkdir(parents=True)
    design = _triple_single_block_request().model_dump()
    (passed_dir / "input.json").write_text(json.dumps(design), encoding="utf-8")
    (failed_dir / "input.json").write_text(json.dumps(design), encoding="utf-8")
    release = passed_artifacts / "guide.dxf"
    preview = passed_artifacts / "guide.png"
    release.write_bytes(b"release")
    preview.write_bytes(b"preview")
    report = {
        "release_allowed": True,
        "machine": {"machine_id": "triple_single_down_up", "machine_name": "三头机单导轨（下上）"},
        "input_rule": {"groove_profile": "rectangular_groove"},
        "process_parameters": {
            "slot_width": {"slot_width": 8.56},
            "guide_thickness": {"result": 2.22},
        },
        "inspection": {"release_allowed": True},
        "dimension_definition_point_audit": {"release_allowed": True},
        "paths": {"release_dxf": str(release), "preview_png": str(preview)},
        "workflow": ["read_config", "promote_release_dxf_after_validation"],
    }
    (passed_artifacts / "guide_report.json").write_text(json.dumps(report), encoding="utf-8")

    result = list_tasks(limit=100, user=user)

    assert result["metrics"] == {"total": 2, "today": 2, "passed": 1, "failed": 1, "running": 0}
    passed = next(item for item in result["items"] if item["task_id"] == "abc123def456")
    failed = next(item for item in result["items"] if item["task_id"] == "def456abc123")
    assert passed["derived"] == {
        "slot_width": 8.56,
        "guide_thickness": 2.22,
        "groove_profile": "rectangular_groove",
    }
    assert passed["files"]["release_dxf"]["name"] == "guide.dxf"
    assert passed["can_delete"] is True
    assert failed["status"] == "failed"
    assert "report.json" in failed["error"]

    detail = get_task("abc123def456", user=user)
    assert detail["input"]["finished_spec"] == design["finished_spec"]
    assert detail["audit"]["inspection_passed"] is True
    assert detail["audit"]["dimension_points_passed"] is True


def test_task_repository_persists_failure_reason(tmp_path: Path) -> None:
    task_dir = tmp_path / "abc123def456"
    task_dir.mkdir()
    (task_dir / "input.json").write_text(json.dumps(_triple_single_block_request().model_dump()), encoding="utf-8")
    repository = WebTaskRepository(tmp_path)
    repository.initialize(task_dir, task_id=task_dir.name, created_by="operator")
    repository.finish(task_dir, status="failed", error="尺寸定义点审计未通过")

    record = repository.get(task_dir.name)

    assert record is not None
    assert record.status == "failed"
    assert record.error == "尺寸定义点审计未通过"
    assert record.created_by == "operator"


def test_task_repository_deletes_only_expired_completed_tasks(tmp_path: Path) -> None:
    now = datetime(2026, 7, 15, tzinfo=timezone.utc)
    repository = WebTaskRepository(tmp_path)
    for task_id, created_at, task_status in (
        ("oldpassed001", "2026-06-14T00:00:00+00:00", "passed"),
        ("newpassed001", "2026-06-16T00:00:00+00:00", "passed"),
        ("oldrunning01", "2026-06-01T00:00:00+00:00", "running"),
    ):
        task_dir = tmp_path / task_id
        task_dir.mkdir()
        (task_dir / "input.json").write_text(json.dumps(_triple_single_block_request().model_dump()), encoding="utf-8")
        (task_dir / "task_status.json").write_text(
            json.dumps({
                "task_id": task_id,
                "status": task_status,
                "created_at": created_at,
                "updated_at": created_at,
                "created_by": "admin",
                "error": None,
            }),
            encoding="utf-8",
        )

    deleted = repository.delete_expired(30, now=now)

    assert deleted == ["oldpassed001"]
    assert not (tmp_path / "oldpassed001").exists()
    assert (tmp_path / "newpassed001").is_dir()
    assert (tmp_path / "oldrunning01").is_dir()


def test_local_administrator_can_delete_owned_legacy_and_other_users_tasks(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(web_api, "WEB_OUTPUT_ROOT", tmp_path)
    repository = WebTaskRepository(tmp_path)
    for task_id, owner in (
        ("abc123def456", "operator"),
        ("def456abc123", "other-operator"),
        ("legacy123456", None),
    ):
        task_dir = tmp_path / task_id
        task_dir.mkdir()
        (task_dir / "input.json").write_text(
            json.dumps(_triple_single_block_request().model_dump()),
            encoding="utf-8",
        )
        if owner is not None:
            repository.initialize(task_dir, task_id=task_id, created_by=owner)
            repository.finish(task_dir, status="passed")

    result = delete_task("abc123def456", user=LOCAL_ADMIN)
    assert result == {"task_id": "abc123def456", "status": "deleted"}
    assert not (tmp_path / "abc123def456").exists()

    for task_id in ("def456abc123", "legacy123456"):
        assert delete_task(task_id, user=LOCAL_ADMIN) == {"task_id": task_id, "status": "deleted"}
        assert not (tmp_path / task_id).exists()


def test_bulk_delete_returns_deleted_and_skipped_tasks(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(web_api, "WEB_OUTPUT_ROOT", tmp_path)
    repository = WebTaskRepository(tmp_path)
    for task_id, owner, task_status in (
        ("owned1234567", "operator", "passed"),
        ("other1234567", "other-operator", "passed"),
        ("running12345", "operator", "running"),
    ):
        task_dir = tmp_path / task_id
        task_dir.mkdir()
        (task_dir / "input.json").write_text(
            json.dumps(_triple_single_block_request().model_dump()),
            encoding="utf-8",
        )
        repository.initialize(task_dir, task_id=task_id, created_by=owner)
        if task_status == "passed":
            repository.finish(task_dir, status="passed")

    result = bulk_delete_tasks(
        BulkDeleteRequest(
            task_ids=["owned1234567", "other1234567", "running12345", "missing12345"]
        ),
        user=LOCAL_ADMIN,
    )

    assert result["deleted"] == ["owned1234567", "other1234567"]
    assert [item["task_id"] for item in result["skipped"]] == [
        "running12345",
        "missing12345",
    ]
    assert not (tmp_path / "owned1234567").exists()
    assert not (tmp_path / "other1234567").exists()
    assert (tmp_path / "running12345").is_dir()


def test_task_file_payload_only_exposes_generated_task_files(tmp_path: Path) -> None:
    task_dir = tmp_path / "abc123def456"
    preview = task_dir / "artifacts" / "preview" / "guide.png"
    report = task_dir / "artifacts" / "reports" / "guide_report.json"
    preview.parent.mkdir(parents=True)
    report.parent.mkdir(parents=True)
    preview.write_bytes(b"preview")
    report.write_text("{}", encoding="utf-8")

    payload = _task_file_payload(
        "abc123def456",
        task_dir,
        {"paths": {"preview_png": str(preview)}},
    )

    assert payload["preview_png"]["url"].endswith("/artifacts/preview/guide.png")
    assert payload["report_json"]["name"] == "guide_report.json"


def test_local_administrator_file_payload_exposes_audit_artifacts(tmp_path: Path) -> None:
    task_dir = tmp_path / "abc123def456"
    dxf_dir = task_dir / "artifacts" / "dxf"
    preview_dir = task_dir / "artifacts" / "preview"
    report_dir = task_dir / "artifacts" / "reports"
    dxf_dir.mkdir(parents=True)
    preview_dir.mkdir(parents=True)
    report_dir.mkdir(parents=True)
    release = dxf_dir / "guide.dxf"
    debug = dxf_dir / "guide（调试）.dxf"
    preview = preview_dir / "guide.png"
    audit = report_dir / "guide_dimension_definition_point_audit.json"
    release.write_bytes(b"release")
    debug.write_bytes(b"debug")
    preview.write_bytes(b"preview")
    audit.write_text("{}", encoding="utf-8")
    report = {"paths": {"release_dxf": str(release), "debug_dxf": str(debug), "preview_png": str(preview)}}

    payload = _task_file_payload(
        "abc123def456",
        task_dir,
        report,
        user=LOCAL_ADMIN,
    )

    assert set(payload) == {"release_dxf", "debug_dxf", "preview_png", "dimension_audit"}
    assert payload["release_dxf"]["name"] == "guide.dxf"


def test_local_identity_is_always_administrator() -> None:
    assert require_user(object()) == LOCAL_ADMIN
    assert LOCAL_ADMIN.is_administrator is True


def test_http_api_uses_local_administrator_without_login(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(web_api, "WEB_OUTPUT_ROOT", tmp_path)
    task_dir = tmp_path / "abc123def456" / "artifacts"
    dxf_dir = task_dir / "dxf"
    preview_dir = task_dir / "preview"
    report_dir = task_dir / "reports"
    dxf_dir.mkdir(parents=True)
    preview_dir.mkdir(parents=True)
    report_dir.mkdir(parents=True)
    release = dxf_dir / "guide.dxf"
    debug = dxf_dir / "guide-debug.dxf"
    preview = preview_dir / "guide.png"
    release.write_bytes(b"release")
    debug.write_bytes(b"debug")
    preview.write_bytes(b"preview")
    (report_dir / "guide_report.json").write_text(
        json.dumps({"paths": {"release_dxf": str(release), "preview_png": str(preview)}}),
        encoding="utf-8",
    )

    me_status, _, me_body = _call_asgi("GET", "/api/auth/me")
    machine_status, _, _ = _call_asgi("GET", "/api/machines")
    release_status, _, _ = _call_asgi(
        "GET", "/api/tasks/abc123def456/files/artifacts/dxf/guide.dxf"
    )
    debug_status, _, _ = _call_asgi(
        "GET", "/api/tasks/abc123def456/files/artifacts/dxf/guide-debug.dxf"
    )

    assert me_status == 200
    assert json.loads(me_body) == {"username": "local-admin", "role": "administrator"}
    assert machine_status == 200
    assert release_status == 200
    assert debug_status == 200
