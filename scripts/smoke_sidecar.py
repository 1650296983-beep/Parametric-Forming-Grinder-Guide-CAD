#!/usr/bin/env python3
"""Start a packaged sidecar, verify localhost health, then ensure it exits."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    parser.add_argument("--narrow-block", action="store_true", help="Generate both reported narrow-block cases with the packaged engine.")
    parser.add_argument("--data-root", type=Path, help="Keep smoke-test artifacts at a known diagnostic path.")
    args = parser.parse_args()
    data_root = args.data_root or Path(tempfile.mkdtemp(prefix="成型磨CAD-"))
    data_root.mkdir(parents=True, exist_ok=True)
    status_file = data_root / "temp" / "sidecar-status.json"
    environment = {**os.environ, "CAD_DESKTOP_MODE": "1", "CAD_APP_DATA_ROOT": str(data_root)}
    process = subprocess.Popen(
        [str(args.executable.resolve()), "--port", "0", "--status-file", str(status_file)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=environment,
    )
    generation_checks = []
    try:
        deadline = time.monotonic() + 60
        while not status_file.is_file():
            if process.poll() is not None:
                raise RuntimeError("sidecar exited before writing its status file")
            if time.monotonic() >= deadline:
                raise TimeoutError("sidecar did not write status file")
            time.sleep(0.1)
        payload = json.loads(status_file.read_text(encoding="utf-8"))
        assert payload["event"] == "sidecar_listening"
        port = int(payload["port"])
        deadline = time.monotonic() + 60
        while True:
            try:
                with urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1) as response:
                    assert json.load(response) == {"status": "ok"}
                    break
            except OSError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.1)
        expected = {"tasks", "output", "temp", "logs"}
        assert expected <= {path.name for path in data_root.iterdir()}
        if args.narrow_block:
            for machine_id, wheels, relief, nominal_width, slot_width in (
                ("double_head_up_up", ["上", "上"], "4-1", 3.05, 3.03),
                ("double_head_up_down", ["上", "下"], "4-1", 3.05, 3.03),
            ):
                started = time.monotonic()
                print(json.dumps({"generation_started": machine_id, "data_root": str(data_root)}, ensure_ascii=True), flush=True)
                design = {
                    "machine_type": machine_id,
                    "guide_rail_type": "single_guide",
                    "wheel_sequence": wheels,
                    "first_wheel_side": "upper",
                    "template_coordinate_system": "section_xy_y_up",
                    "finished_spec": f"R13.2*{nominal_width}*5.6*0.9",
                    "pre_grinding_spec": f"5.6*{nominal_width}（-0.04/-0.055）*0.93（+0.01/-0.01）",
                    "product_shape_after": "bread_shape",
                    "product_shape_before": "rectangular_block",
                    "high_symmetry_requirement": True,
                    "relief": relief,
                }
                invalid = {**design, "finished_spec": "R13.2*2.55*5.6*0.9", "pre_grinding_spec": "5.6*2.55（-0.04/-0.055）*0.93（+0.01/-0.01）", "relief": "4-1"}
                for route, payload in (("validate", invalid), ("generate", {"design": invalid})):
                    rejected = Request(
                        f"http://127.0.0.1:{port}/api/designs/{route}",
                        data=json.dumps(payload, ensure_ascii=True).encode("utf-8"),
                        headers={"Content-Type": "application/json"}, method="POST",
                    )
                    try:
                        with urlopen(rejected, timeout=30):
                            raise AssertionError("Invalid 2.53 mm / 4-1 input was accepted")
                    except HTTPError as error:
                        assert error.code == 422
                        assert "槽宽 2.53 mm" in json.load(error)["detail"]
                request = Request(
                    f"http://127.0.0.1:{port}/api/designs/generate",
                    data=json.dumps({"design": design}, ensure_ascii=True).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request, timeout=300) as response:
                    result = json.load(response)
                assert result["ok"] and result["release_allowed"], result.get("stderr")
                report = result["report"]
                audit = report["dimension_definition_point_audit"]
                assert audit["release_allowed"] and audit["all_dimensions_bound_to_geometry"]
                assert report["process_parameters"]["slot_width"]["slot_width"] == slot_width
                assert report["process_parameters"]["guide_thickness"]["result"] == 1.05
                assert report["fixed_template_dimensions"]["section"]["center_opening"] == 0.90
                assert Path(report["paths"]["release_dxf"]).is_file()
                generation_checks.append({
                    "machine_id": machine_id,
                    "release_allowed": True,
                    "dimension_count": audit["dimension_count"],
                    "max_point_error": max(item["point_error"] for item in audit["dimensions"]),
                    "elapsed_seconds": round(time.monotonic() - started, 2),
                })
                print(json.dumps(generation_checks[-1]), flush=True)
    except Exception:
        print(json.dumps({"smoke_failure_files": [
            str(path.relative_to(data_root)) for path in data_root.rglob("*") if path.is_file()
        ]}, ensure_ascii=True), flush=True)
        for report_path in data_root.glob("tasks/**/*_report.json"):
            report = json.loads(report_path.read_text(encoding="utf-8"))
            print(json.dumps({
                "report": str(report_path), "release_allowed": report.get("release_allowed"),
                "failed_dimensions": [item for item in report.get("dimension_definition_point_audit", {}).get("dimensions", []) if not item.get("bound_to_geometry", True)],
            }, ensure_ascii=True), flush=True)
        raise
    finally:
        if process.poll() is None and "port" in locals():
            try:
                urlopen(Request(f"http://127.0.0.1:{port}/api/desktop/shutdown", method="POST"), timeout=2).close()
            except OSError:
                process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    if process.poll() is None:
        raise SystemExit("sidecar process remains after termination")
    print(
        json.dumps(
            {
                "health": "ok",
                "terminated": True,
                "unicode_data_root": str(data_root),
                "generation_checks": generation_checks,
            },
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
