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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    args = parser.parse_args()
    data_root = Path(tempfile.mkdtemp(prefix="成型磨CAD-"))
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
            },
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
