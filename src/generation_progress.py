"""Persisted real CAD generation boundaries; no timing-based progress."""
from __future__ import annotations
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from uuid import uuid4
from typing import Any

_PROGRESS: ContextVar[Path | None] = ContextVar('cad_generation_progress', default=None)
FILENAME = 'generation_progress.json'
MESSAGES = {'queued': '等待前一个任务完成', 'preparing': '正在读取机台与磨前参数', 'outline': '导轨外形已重建', 'cavity': '真实型腔、六处避空和侧视已重建', 'dimensions': '尺寸已绑定真实几何', 'candidate': '正在生成正式候选图', 'preview': '正在生成预览', 'validation': '正在校验几何与尺寸', 'promotion': '正在晋级通过校验的图纸', 'complete': '图纸已通过校验并输出'}


@contextmanager
def progress_context(task_dir: Path):
    token = _PROGRESS.set(task_dir / FILENAME)
    try:
        yield
    finally:
        _PROGRESS.reset(token)


def progress_path() -> Path | None:
    current = _PROGRESS.get()
    if current is not None:
        return current
    configured = os.getenv('CAD_GENERATION_PROGRESS_FILE')
    return Path(configured) if configured else None


def read_progress(task_dir: Path) -> dict[str, Any] | None:
    try:
        return json.loads((task_dir / FILENAME).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def _write(path: Path, payload: dict) -> None:
    temporary = path.with_name(f'.{path.name}.{uuid4().hex}.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


def emit(stage: str, *, scene: dict | None = None, error: str | None = None, result: dict | None = None, complete: bool = False) -> None:
    path = progress_path()
    if path is None:
        return
    payload = read_progress(path.parent) or {'task_id': path.parent.name, 'events': [], 'scene': None, 'result': None, 'error': None}
    now = datetime.now(timezone.utc).isoformat()
    events = payload['events']
    if events and events[-1]['status'] == 'running' and (error or events[-1]['stage'] != stage):
        events[-1]['status'] = 'failed' if error else 'completed'
    message = error or MESSAGES[stage]
    if not error and not (events and events[-1]['stage'] == stage):
        events.append({'stage': stage, 'status': 'completed' if complete else 'running', 'at': now, 'message': message})
    payload.update(stage=stage, status='failed' if error else ('passed' if complete else 'running'), message=message, error=error, events=events[-40:])
    if scene is not None:
        payload['scene'] = scene
    if result is not None:
        payload['result'] = result
    _write(path, payload)


def fail(message: str, *, result: dict | None = None) -> None:
    path = progress_path()
    payload = read_progress(path.parent) if path else None
    emit(payload.get('stage', 'preparing') if payload else 'preparing', error=message, result=result)


def geometry_ready(filename: Path, machine: Any) -> None:
    if progress_path() is None:
        return
    from .drawing_scene import scene_from_dxf
    scene = scene_from_dxf(filename, machine, source='debug_dxf')
    for stage, groups in [('outline', {'outline', 'center'}), ('cavity', {'outline', 'center', 'cavity'}), ('dimensions', {'outline', 'center', 'cavity', 'dimensions'})]:
        partial = {**scene, 'views': [{**view, 'primitives': [p for p in view['primitives'] if p['group'] in groups]} for view in scene['views']]}
        emit(stage, scene=partial)
