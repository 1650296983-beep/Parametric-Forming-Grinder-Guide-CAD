"""Stable locations for version-controlled CAD source templates."""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LEGACY_TEMPLATE_ROOT = PROJECT_ROOT / "templates" / "legacy_reference"


def legacy_template_path(filename: str) -> Path:
    """Return one required legacy template without depending on the working directory."""
    return LEGACY_TEMPLATE_ROOT / filename
