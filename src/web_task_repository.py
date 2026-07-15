"""Persistence helpers for Web generation task history.

The generated task directory remains the source of truth.  This repository
only adds lifecycle metadata and reconstructs legacy records from ``input.json``
and ``report.json`` when the metadata file does not exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
from typing import Any, Literal


TaskStatus = Literal["running", "passed", "failed"]
TASK_STATUS_FILENAME = "task_status.json"


@dataclass(frozen=True)
class StoredWebTask:
    task_id: str
    task_dir: Path
    created_at: str
    updated_at: str
    status: TaskStatus
    design: dict[str, Any]
    report: dict[str, Any] | None
    error: str | None
    created_by: str | None


class WebTaskRepository:
    """Read and update task records stored below one Web output root."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def initialize(
        self,
        task_dir: Path,
        *,
        task_id: str,
        created_by: str | None,
    ) -> None:
        now = _utc_now()
        self._write_status(
            task_dir,
            {
                "task_id": task_id,
                "status": "running",
                "created_at": now,
                "updated_at": now,
                "created_by": created_by,
                "error": None,
            },
        )

    def finish(
        self,
        task_dir: Path,
        *,
        status: Literal["passed", "failed"],
        error: str | None = None,
    ) -> None:
        current = _read_json(task_dir / TASK_STATUS_FILENAME) or {}
        now = _utc_now()
        self._write_status(
            task_dir,
            {
                **current,
                "task_id": task_dir.name,
                "status": status,
                "created_at": current.get("created_at", now),
                "updated_at": now,
                "created_by": current.get("created_by"),
                "error": error,
            },
        )

    def list(self) -> list[StoredWebTask]:
        if not self.root.is_dir():
            return []
        records = [
            record
            for task_dir in self.root.iterdir()
            if task_dir.is_dir()
            and not task_dir.is_symlink()
            and (record := self._read_task(task_dir)) is not None
        ]
        return sorted(records, key=lambda item: item.created_at, reverse=True)

    def get(self, task_id: str) -> StoredWebTask | None:
        if not _valid_task_id(task_id):
            return None
        task_dir = self.root / task_id
        if not task_dir.is_dir() or task_dir.is_symlink():
            return None
        return self._read_task(task_dir)

    def delete(self, task_id: str) -> bool:
        """Delete one validated task directory without following symlinks."""
        record = self.get(task_id)
        if record is None:
            return False
        shutil.rmtree(record.task_dir)
        return True

    def delete_expired(
        self,
        retention_days: int,
        *,
        now: datetime | None = None,
    ) -> list[str]:
        """Delete completed tasks whose creation time is outside retention."""
        if retention_days < 1:
            raise ValueError("retention_days must be at least 1")
        reference_time = now or datetime.now(tz=timezone.utc)
        if reference_time.tzinfo is None:
            reference_time = reference_time.replace(tzinfo=timezone.utc)
        cutoff = reference_time - timedelta(days=retention_days)
        deleted: list[str] = []
        for record in self.list():
            if record.status == "running":
                continue
            created_at = datetime.fromisoformat(record.created_at.replace("Z", "+00:00"))
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            if created_at > cutoff:
                continue
            if self.delete(record.task_id):
                deleted.append(record.task_id)
        return deleted

    def _read_task(self, task_dir: Path) -> StoredWebTask | None:
        input_path = task_dir / "input.json"
        design = _read_json(input_path)
        if design is None:
            return None

        status_data = _read_json(task_dir / TASK_STATUS_FILENAME) or {}
        report_path = next(task_dir.glob("**/*_report.json"), None)
        report = _read_json(report_path) if report_path is not None else None
        created_at = _timestamp_or_file_time(status_data.get("created_at"), input_path)
        updated_source = report_path or task_dir / TASK_STATUS_FILENAME
        if not updated_source.exists():
            updated_source = input_path
        updated_at = _timestamp_or_file_time(status_data.get("updated_at"), updated_source)
        status = _resolve_status(status_data.get("status"), report)
        error = status_data.get("error")
        if status == "failed" and not error and report is None:
            error = "任务未生成 report.json；请检查输入或重新生成。"

        return StoredWebTask(
            task_id=task_dir.name,
            task_dir=task_dir,
            created_at=created_at,
            updated_at=updated_at,
            status=status,
            design=design,
            report=report,
            error=str(error) if error else None,
            created_by=(str(status_data["created_by"]) if status_data.get("created_by") else None),
        )

    @staticmethod
    def _write_status(task_dir: Path, payload: dict[str, Any]) -> None:
        target = task_dir / TASK_STATUS_FILENAME
        temporary = task_dir / f".{TASK_STATUS_FILENAME}.tmp"
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(target)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _resolve_status(raw_status: Any, report: dict[str, Any] | None) -> TaskStatus:
    if raw_status in {"running", "passed", "failed"}:
        return raw_status
    if report is not None:
        return "passed" if bool(report.get("release_allowed")) else "failed"
    return "failed"


def _timestamp_or_file_time(raw_timestamp: Any, path: Path) -> str:
    if isinstance(raw_timestamp, str):
        try:
            datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
            return raw_timestamp
        except ValueError:
            pass
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _valid_task_id(task_id: str) -> bool:
    return task_id.isalnum() and len(task_id) == 12
