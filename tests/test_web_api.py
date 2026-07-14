from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import src.web_api as web_api
from src.auth import AuthenticatedUser, authenticate, create_session_token, require_user
from src.web_api import (
    DesignInput,
    GenerationRequest,
    _task_file_payload,
    generate_design,
    list_machines,
    validate_design,
)


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


def test_operator_file_payload_exposes_only_release_dxf(tmp_path: Path) -> None:
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
        user=AuthenticatedUser(username="operator", role="operator"),
    )

    assert set(payload) == {"release_dxf"}
    assert payload["release_dxf"]["name"] == "guide.dxf"


def test_environment_configured_session_preserves_server_role(monkeypatch) -> None:
    monkeypatch.setenv("CAD_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("CAD_ADMIN_PASSWORD", "admin-password")
    monkeypatch.setenv("CAD_SESSION_SECRET", "session-signing-secret")
    monkeypatch.setenv("CAD_OPERATOR_ACCOUNTS_JSON", '{"operator":"operator-password"}')

    administrator = authenticate("admin", "admin-password")
    operator = authenticate("operator", "operator-password")

    assert administrator == AuthenticatedUser(username="admin", role="administrator")
    assert operator == AuthenticatedUser(username="operator", role="operator")
    assert authenticate("operator", "wrong-password") is None
    token = create_session_token(operator)
    request = SimpleNamespace(cookies={"cad_session": token})
    assert require_user(request) == operator


def test_http_authentication_and_operator_artifact_guard(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(web_api, "WEB_OUTPUT_ROOT", tmp_path)
    monkeypatch.setenv("CAD_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("CAD_ADMIN_PASSWORD", "admin-password")
    monkeypatch.setenv("CAD_SESSION_SECRET", "session-signing-secret")
    monkeypatch.setenv("CAD_OPERATOR_ACCOUNTS_JSON", '{"operator":"operator-password"}')
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

    unauthorized_status, _, _ = _call_asgi("GET", "/api/machines")
    login_status, login_headers, login_body = _call_asgi(
        "POST",
        "/api/auth/login",
        body=b'{"username":"operator","password":"operator-password"}',
        headers={"content-type": "application/json"},
    )
    cookie = login_headers["set-cookie"].split(";", 1)[0]
    machine_status, _, _ = _call_asgi("GET", "/api/machines", headers={"cookie": cookie})
    release_status, _, _ = _call_asgi(
        "GET", "/api/tasks/abc123def456/files/artifacts/dxf/guide.dxf", headers={"cookie": cookie}
    )
    debug_status, _, _ = _call_asgi(
        "GET", "/api/tasks/abc123def456/files/artifacts/dxf/guide-debug.dxf", headers={"cookie": cookie}
    )

    assert unauthorized_status == 401
    assert login_status == 200
    assert json.loads(login_body) == {"username": "operator", "role": "operator"}
    assert machine_status == 200
    assert release_status == 200
    assert debug_status == 403
