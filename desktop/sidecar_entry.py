"""PyInstaller/Tauri entry point for the localhost-only FastAPI sidecar."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import sys

from desktop.runtime_paths import get_runtime_paths
from desktop.version import APP_VERSION


def _serve(port: int, status_file: Path | None) -> int:
    os.environ.setdefault("CAD_DESKTOP_MODE", "1")
    runtime = get_runtime_paths()
    os.environ["CAD_APP_DATA_ROOT"] = str(runtime.app_data_root)
    os.environ["MPLCONFIGDIR"] = str(runtime.temp / "matplotlib")
    Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)

    import uvicorn
    from src.web_api import app

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", port))
    listener.listen(128)
    selected_port = int(listener.getsockname()[1])
    payload = {
        "event": "sidecar_listening",
        "host": "127.0.0.1",
        "port": selected_port,
        "version": APP_VERSION,
    }
    if status_file is not None:
        status_file.parent.mkdir(parents=True, exist_ok=True)
        temporary_status = status_file.with_suffix(".tmp")
        temporary_status.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
        temporary_status.replace(status_file)
    if sys.stdout is not None:
        print(json.dumps(payload, ensure_ascii=True), flush=True)
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=selected_port,
        log_level="warning",
        access_log=False,
        server_header=False,
    )
    server = uvicorn.Server(config)
    app.state.request_desktop_shutdown = lambda: setattr(server, "should_exit", True)
    server.run(sockets=[listener])
    if status_file is not None:
        status_file.unlink(missing_ok=True)
    return 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "generate-machine":
        # Frozen child-process dispatch for the existing isolated generator.
        from src.generate_machine import main as generate_machine_main

        sys.argv = [sys.argv[0], *sys.argv[2:]]
        return generate_machine_main()

    parser = argparse.ArgumentParser(description="Forming Grinder CAD localhost sidecar")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--status-file", type=Path)
    parser.add_argument("--version", action="store_true")
    args = parser.parse_args()
    if args.version:
        print(APP_VERSION)
        return 0
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    return _serve(args.port, args.status_file)


if __name__ == "__main__":
    raise SystemExit(main())
