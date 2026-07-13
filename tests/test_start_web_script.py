from __future__ import annotations

from pathlib import Path
import subprocess


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_start_web_script_has_valid_bash_syntax() -> None:
    script = PROJECT_ROOT / "scripts" / "start_web.sh"

    result = subprocess.run(
        ["bash", "-n", str(script)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
