from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .global_rules import format_dimension


_PLAIN_NUMBER = re.compile(r"^[+-]?\d+(?:\.\d+)?$")
_RADIUS_NUMBER = re.compile(r"^[Rr]([+-]?\d+(?:\.\d+)?)$")


def normalize_dimension_display_precision(doc: Any, modelspace: Any) -> None:
    """Write all ordinary dimension values with exactly two decimals."""
    for dimension in modelspace.query("DIMENSION"):
        raw_text = (
            str(dimension.dxf.text).strip()
            if dimension.dxf.hasattr("text")
            else ""
        )
        if raw_text and raw_text not in {"<>", ""}:
            normalized = _normalize_explicit_text(raw_text)
            if normalized is None:
                continue
        else:
            try:
                measurement = float(dimension.get_measurement())
            except Exception:
                continue
            dimtype = int(dimension.dxf.dimtype) & 15
            normalized = (
                f"R{format_dimension(measurement)}"
                if dimtype == 4
                else format_dimension(measurement)
            )
        dimension.dxf.text = normalized
        _set_dimension_block_text(doc, dimension, normalized)


def build_dimension_precision_audit(modelspace: Any) -> dict[str, Any]:
    invalid = []
    checked = 0
    for dimension in modelspace.query("DIMENSION"):
        text = str(dimension.dxf.text).strip()
        if "<>" in text or "±" in text or "\\S" in text:
            continue
        if _PLAIN_NUMBER.fullmatch(text):
            checked += 1
            if not re.fullmatch(r"[+-]?\d+\.\d{2}", text):
                invalid.append({"handle": dimension.dxf.handle, "text": text})
        elif _RADIUS_NUMBER.fullmatch(text):
            checked += 1
            if not re.fullmatch(r"[Rr][+-]?\d+\.\d{2}", text):
                invalid.append({"handle": dimension.dxf.handle, "text": text})
    return {
        "checked_dimension_count": checked,
        "invalid_dimensions": invalid,
        "release_allowed": not invalid,
    }


def build_dimension_precision_file_audit(
    dxf_path: str | Path,
) -> dict[str, Any]:
    import ezdxf

    doc = ezdxf.readfile(dxf_path)
    return build_dimension_precision_audit(doc.modelspace())


def _normalize_explicit_text(text: str) -> str | None:
    if "<>" in text or "±" in text or "\\S" in text:
        return None
    if match := _PLAIN_NUMBER.fullmatch(text):
        return format_dimension(float(match.group(0)))
    if match := _RADIUS_NUMBER.fullmatch(text):
        return f"R{format_dimension(float(match.group(1)))}"
    return None


def _set_dimension_block_text(doc: Any, dimension: Any, text: str) -> None:
    if not dimension.dxf.hasattr("geometry"):
        return
    block_name = dimension.dxf.geometry
    if block_name not in doc.blocks:
        return
    for entity in doc.blocks[block_name]:
        if entity.dxftype() == "TEXT":
            entity.dxf.text = text
        elif entity.dxftype() == "MTEXT":
            entity.text = text
