from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from math import hypot
from pathlib import Path
from threading import BoundedSemaphore, Event
import json

import ezdxf
from fastapi import HTTPException
import pytest

import src.web_api as api
from src.auth import LOCAL_ADMIN
from src.drawing_scene import preview_scene, scene_from_dxf
from src.generation_progress import emit, fail, geometry_ready, progress_context, read_progress
from src.machine_config import load_machine_config
from src.web_task_repository import WebTaskRepository

MACHINES = tuple(path.parent.name for path in sorted(api.TEMPLATE_ROOT.glob('*/config.yaml')))


def design(machine_id='triple_single_down_up', shape='block_bread'):
    machine = load_machine_config(machine_id)
    data = dict(machine_type=machine.machine_id, guide_rail_type=machine.guide_type,
                wheel_sequence=list(machine.wheel_positions), first_wheel_side={'上': 'upper', '下': 'lower'}[machine.wheel_positions[0]],
                template_coordinate_system=machine.template_coordinate_system,
                finished_spec='R9.6*8.6*42.6*2.1', pre_grinding_spec='42.6*8.6(-0.07/-0.09)*2.1(+0.01/-0.01)',
                product_shape_after='bread_shape', product_shape_before='rectangular_block')
    if shape != 'block_bread':
        data.update(finished_spec='R30*R28*6*9.1*2.1', product_shape_after='tile_shape', pre_grinding_spec='9.1*6(-0.01/-0.02)*2.25(+0.01/-0.01)')
    if shape == 'same_r_tile':
        data.update(pre_grinding_spec='R30*R30*6(-0.01/-0.02)*9.1*2.25(+0.01/-0.01)', product_shape_before='same_r_tile')
    return api.DesignInput(**data)


@pytest.mark.parametrize('machine_id', MACHINES)
@pytest.mark.parametrize('shape', ('block_bread', 'block_tile', 'same_r_tile'))
def test_preview_uses_real_six_arc_sections_and_wheel_geometry(tmp_path, machine_id, shape):
    """Source handles, endpoints and radii independently match actual DXF arcs."""
    machine = load_machine_config(machine_id)
    _, _, profile, _ = api._build_profile_for_design(design(machine_id, shape), machine)
    filename = tmp_path / 'writer.dxf'
    if machine.guide_sections == 2:
        api.DualGuideTemplateEngine(machine).write_dxf(profile, filename, output_mode='debug')
    else:
        from src.dxf_writer import write_dxf
        write_dxf(profile, filename, output_mode='debug', machine_config_override=machine)
    scene = scene_from_dxf(filename, machine, source='debug_dxf')
    actual = ezdxf.readfile(filename)
    by_handle = {entity.dxf.handle: entity for entity in actual.modelspace().query('ARC')}
    sections = [view for view in scene['views'] if view['id'].startswith('section')]
    assert len(sections) == machine.guide_sections
    for view in sections:
        small_arcs = [by_handle[p['id']] for p in view['primitives'] if p['id'] in by_handle and abs(by_handle[p['id']].dxf.radius - 0.5) < 1e-9]
        assert len(small_arcs) == 6
        assert view['bounds'][2] - view['bounds'][0] < 130
        texts = {p['text'] for p in view['primitives'] if p['kind'] == 'text'}
        # These dimensions have leaders far beyond the section silhouette. They
        # must survive view selection and keep audited parent labels/tolerances.
        guide = profile.guide_spec
        expected = [f'{guide.guide_slot_width:.2f}', f'{guide.guide_thickness:.2f}', f'{guide.center_opening:.2f}', f'{guide.outer_height:.2f}', f'{guide.outer_width:.2f}']
        for label in expected:
            native = [e for e in actual.modelspace().query('DIMENSION') if e.dxf.get('text', '').startswith(label)]
            assert native, (machine_id, shape, label)
            candidates = [e for e in native if any(p['id'].startswith(e.dxf.handle+'-') for p in view['primitives'])]
            assert len(candidates) == 1, (machine_id, shape, view['id'], label, texts)
            for parent in candidates:
                explicit = parent.dxf.get('text', '')
                if explicit and '<>' not in explicit:
                    from ezdxf.tools.text import plain_text
                    assert plain_text(explicit) in texts
                    assert '^' not in plain_text(explicit)
        for primitive in view['primitives']:
            if primitive['id'] not in by_handle:
                continue
            arc = by_handle[primitive['id']]
            assert primitive['kind'] == 'polyline'
            for x, y in primitive['points']:
                assert hypot(x-arc.dxf.center.x, -y-arc.dxf.center.y) == pytest.approx(arc.dxf.radius, abs=1e-7)
            assert primitive['points'][0] == pytest.approx([arc.start_point.x, -arc.start_point.y])
            assert primitive['points'][-1] == pytest.approx([arc.end_point.x, -arc.end_point.y])
    sides = [view for view in scene['views'] if view['id'].startswith('side') or view['id'] == 'assembly']
    assert len(sides) == (3 if machine.guide_sections == 2 else 1)
    for view in sides:
        wheels = [p for p in view['primitives'] if p['id'] in by_handle and abs(by_handle[p['id']].dxf.radius-machine.wheel_radius) < 1e-7]
        expected = len(machine.wheel_positions) if machine.guide_sections == 1 or view['id'] == 'assembly' else (1 if view['id'] == 'side_1' else 2)
        assert len(wheels) == expected
        for primitive in wheels:
            arc = by_handle[primitive['id']]
            assert primitive['points'][0] == pytest.approx([arc.start_point.x, -arc.start_point.y])
            assert primitive['points'][-1] == pytest.approx([arc.end_point.x, -arc.end_point.y])
    dimension_handles = {e.dxf.handle for e in actual.modelspace().query('DIMENSION')}
    owners = {}
    for view in scene['views']:
        selected_parents = {p['id'].split('-')[0] for p in view['primitives']} & dimension_handles
        for handle in selected_parents:
            assert handle not in owners, (machine_id, shape, handle, owners.get(handle), view['id'])
            owners[handle] = view['id']
    assert 'REFERENCE_PROFILE' not in json.dumps(scene)


def test_validation_is_source_labeled_and_explains_reliefs_without_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(api, 'WEB_OUTPUT_ROOT', tmp_path)
    result = api.validate_design(design())
    assert result['scene']['source'] == 'parametric_preview'
    assert result['scene']['units'] == 'mm'
    assert result['derived']['relief_diameter'] == 1
    assert result['derived']['relief_radius'] == .5
    assert result['derived']['center_transition_count'] == 2
    assert result['derived']['opening_max'] == 2
    assert result['parsed']['finished'] and result['parsed']['preform']
    assert not list(tmp_path.iterdir())


@pytest.fixture
def job_environment(tmp_path, monkeypatch):
    worker = ThreadPoolExecutor(max_workers=1)
    monkeypatch.setattr(api, 'WEB_OUTPUT_ROOT', tmp_path)
    monkeypatch.setattr(api, '_GENERATION_WORKER', worker)
    monkeypatch.setattr(api, '_JOB_SLOTS', {})
    monkeypatch.setattr(api, '_JOB_CAPACITY', 9)
    yield tmp_path
    worker.shutdown(wait=True)


@pytest.mark.parametrize('machine_id', ('triple_single_down_up', 'triple_double_down_up_up'))
def test_actual_job_has_one_history_id_snapshot_and_final_release_scene(job_environment, machine_id):
    """Execute both subprocess and in-process engines through their real gates."""
    request = api.GenerationRequest(design=design(machine_id))
    original = request.design.model_dump()
    response = api.create_generation_job(request, LOCAL_ADMIN)
    task_id = response['task_id']
    assert len(task_id) == 12
    request.design.finished_spec = 'MUTATED AFTER SUBMISSION'
    # The future drain is synchronization, never fake progress timing.
    api._GENERATION_WORKER.submit(lambda: None).result(timeout=60)
    progress = api.get_generation_progress(task_id, LOCAL_ADMIN)
    assert progress['status'] == 'passed', progress
    assert progress['stage'] == 'complete'
    assert progress['result']['task_id'] == task_id
    assert progress['scene']['source'] == 'release_dxf'
    records = WebTaskRepository(job_environment).list()
    assert len(records) == 1 and records[0].task_id == task_id
    assert records[0].design == original
    result = progress['result']
    final_path = Path(result['report']['paths']['release_dxf'])
    assert final_path.is_file()
    assert progress['scene'] == scene_from_dxf(final_path, load_machine_config(machine_id), source='release_dxf')
    stages = [event['stage'] for event in progress['events']]
    assert stages == ['queued', 'preparing', 'outline', 'cavity', 'dimensions', 'candidate', 'preview', 'validation', 'promotion', 'complete']
    assert all(event['status'] == 'completed' for event in progress['events'])
    assert result['release_allowed'] is True


def test_failure_keeps_real_stage_and_does_not_expose_candidate(job_environment, monkeypatch):
    def failed_generator(request, user, *, initialized_task):
        emit('candidate')
        emit('validation')
        raise ValueError('dimension point failed')
    monkeypatch.setattr(api, 'generate_design', failed_generator)
    response = api.create_generation_job(api.GenerationRequest(design=design()), LOCAL_ADMIN)
    api._GENERATION_WORKER.submit(lambda: None).result(timeout=10)
    progress = api.get_generation_progress(response['task_id'], LOCAL_ADMIN)
    assert progress['stage'] == 'validation'
    assert progress['status'] == 'failed'
    assert progress['events'][-1]['status'] == 'failed'
    assert progress['result']['release_allowed'] is False
    directory = job_environment / response['task_id']
    for filename in ('正式候选.dxf', 'release.candidate.dxf', 'release_candidate.dxf'):
        (directory/filename).write_text('private candidate')
        with pytest.raises(HTTPException) as error:
            api._resolve_task_file(response['task_id'], filename)
        assert error.value.status_code == 404
    (directory/'debug.dxf').write_text('diagnostics')
    assert api._resolve_task_file(response['task_id'], 'debug.dxf').name == 'debug.dxf'
    with pytest.raises(HTTPException):
        api.get_generation_progress('../bad', LOCAL_ADMIN)


def test_restart_marks_orphan_job_interrupted_preserves_actual_stage(job_environment):
    task_id, task_dir, _ = api._initialize_task(design(), LOCAL_ADMIN)
    with progress_context(task_dir):
        emit('queued')
        emit('candidate')
    api.recover_interrupted_jobs()
    progress = api.get_generation_progress(task_id, LOCAL_ADMIN)
    assert progress['status'] == 'failed'
    assert progress['stage'] == 'candidate'
    assert '中断' in progress['message']
    assert WebTaskRepository(job_environment).get(task_id).status == 'failed'
    assert (task_dir/'input.json').is_file()


def test_queue_is_bounded_and_queued_jobs_keep_separate_snapshots(job_environment, monkeypatch):
    started, release = Event(), Event()
    def blocked_generator(request, user, *, initialized_task):
        started.set()
        assert release.wait(timeout=10)
        return {'ok': False, 'release_allowed': False, 'stderr': request.design.relief}
    monkeypatch.setattr(api, 'generate_design', blocked_generator)
    monkeypatch.setattr(api, 'validate_design', lambda value: {})
    monkeypatch.setattr(api, '_JOB_CAPACITY', 2)
    first = api.create_generation_job(api.GenerationRequest(design=design()), LOCAL_ADMIN)
    assert started.wait(timeout=2)
    second_design = design()
    second_design.relief = '4-0.6'
    second = api.create_generation_job(api.GenerationRequest(design=second_design), LOCAL_ADMIN)
    assert api.get_generation_progress(second['task_id'], LOCAL_ADMIN)['stage'] == 'queued'
    with pytest.raises(HTTPException) as error:
        api.create_generation_job(api.GenerationRequest(design=design()), LOCAL_ADMIN)
    assert error.value.status_code == 503
    assert len(WebTaskRepository(job_environment).list()) == 2
    release.set()
    api._GENERATION_WORKER.submit(lambda: None).result(timeout=10)
    assert api.get_generation_progress(first['task_id'], LOCAL_ADMIN)['error'] == '4-1'
    assert api.get_generation_progress(second['task_id'], LOCAL_ADMIN)['error'] == '4-0.6'


def test_submit_failure_releases_capacity_and_does_not_leave_running_task(job_environment, monkeypatch):
    class RejectedExecutor:
        def submit(self, *args):
            raise RuntimeError('executor stopped')
    monkeypatch.setattr(api, '_GENERATION_WORKER', RejectedExecutor())
    monkeypatch.setattr(api, 'validate_design', lambda value: {})
    monkeypatch.setattr(api, '_JOB_CAPACITY', 1)
    for _ in range(2):
        with pytest.raises(HTTPException) as error:
            api.create_generation_job(api.GenerationRequest(design=design()), LOCAL_ADMIN)
        assert error.value.status_code == 503
    records = WebTaskRepository(job_environment).list()
    assert len(records) == 2
    assert all(record.status == 'failed' for record in records)
    assert all(api.get_generation_progress(record.task_id, LOCAL_ADMIN)['status'] == 'failed' for record in records)


def test_queue_capacity_and_task_paths_are_scoped_to_output_root(job_environment, monkeypatch):
    started, release = Event(), Event()
    def blocked_generator(request, user, *, initialized_task):
        started.set()
        assert release.wait(timeout=10)
        emit('validation')
        return {'ok': False, 'release_allowed': False, 'stderr': str(initialized_task[1].parent)}
    monkeypatch.setattr(api, 'generate_design', blocked_generator)
    monkeypatch.setattr(api, 'validate_design', lambda value: {})
    monkeypatch.setattr(api, '_JOB_CAPACITY', 1)
    first = api.create_generation_job(api.GenerationRequest(design=design()), LOCAL_ADMIN)
    assert started.wait(timeout=2)
    other_root = job_environment / 'other-data-root'
    monkeypatch.setattr(api, 'WEB_OUTPUT_ROOT', other_root)
    second = api.create_generation_job(api.GenerationRequest(design=design()), LOCAL_ADMIN)
    assert api.get_generation_progress(second['task_id'], LOCAL_ADMIN)['stage'] == 'queued'
    assert WebTaskRepository(other_root).get(first['task_id']) is None
    monkeypatch.setattr(api, 'WEB_OUTPUT_ROOT', job_environment)
    with pytest.raises(HTTPException) as error:
        api.create_generation_job(api.GenerationRequest(design=design()), LOCAL_ADMIN)
    assert error.value.status_code == 503
    release.set()
    api._GENERATION_WORKER.submit(lambda: None).result(timeout=10)
    first_progress = api.get_generation_progress(first['task_id'], LOCAL_ADMIN)
    assert first_progress['error'] == str(job_environment.resolve())
    monkeypatch.setattr(api, 'WEB_OUTPUT_ROOT', other_root)
    second_progress = api.get_generation_progress(second['task_id'], LOCAL_ADMIN)
    assert second_progress['error'] == str(other_root.resolve())
    assert WebTaskRepository(job_environment).get(first['task_id']).status == 'failed'
    assert WebTaskRepository(other_root).get(second['task_id']).status == 'failed'
