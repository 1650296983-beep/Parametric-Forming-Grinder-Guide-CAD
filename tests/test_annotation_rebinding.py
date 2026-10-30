import ezdxf
import pytest

from src.dimension_writer import _set_linear_definition
from src.dxf_writer import TemplateAnchor, _is_block_template_param_entity


@pytest.mark.parametrize('epsilon', [0, 6e-14, -6e-14, 0.0005])
def test_template_neck_removed_despite_boundary_roundoff(epsilon):
    doc = ezdxf.new()
    anchor = TemplateAnchor(3222, 3262, -120, -93, 3242)
    neck = doc.modelspace().add_line((3241, -93 + epsilon), (3241, -105))
    frame = doc.modelspace().add_line((3222, -120), (3222, -93))
    assert _is_block_template_param_entity(neck, anchor)
    assert not _is_block_template_param_entity(frame, anchor)


def test_up_up_tile_annotations_follow_current_section(tmp_path):
    from src.dual_guide_input import build_dual_guide_profile_from_input
    from src.machine_config import load_machine_config
    from src.dxf_writer import write_dxf, _extract_block_template_anchor
    machine = load_machine_config('triple_single_up_up')
    _, _, profile, _ = build_dual_guide_profile_from_input({
        'finished_product_spec': 'R19.17*R39*5.33*16*2',
        'pre_grinding_spec': 'R19.17*R19.17*5.36(+0/-0.02)*16*2.24(+0/-0.02)',
        'finished_product_shape': 'tile', 'pre_grinding_shape': 'same_r_tile',
        'guide_profile_source': 'pre_grinding_spec',
    }, machine)
    path = write_dxf(profile, tmp_path / 'candidate.dxf', machine_config_override=machine, output_mode='release')
    doc = ezdxf.readfile(path)
    anchor = _extract_block_template_anchor(doc.modelspace())
    dimensions = [d for d in doc.modelspace().query('DIMENSION') if d.dxf.text == '40.00']
    assert len(dimensions) == 1
    assert 0 < dimensions[0].dxf.defpoint.y - anchor.top < 35


def test_real_dual_template_old_neck_is_removed():
    from src.machine_config import load_machine_config
    from src.dxf_writer import _extract_block_template_anchor
    machine = load_machine_config('triple_double_down_up_up')
    doc = ezdxf.readfile(machine.section_template_path)
    anchor = _extract_block_template_anchor(doc.modelspace())
    necks = [e for e in doc.modelspace().query('LINE')
             if abs(e.dxf.start.x - e.dxf.end.x) < 1e-8
             and abs(abs(e.dxf.start.x - anchor.slot_center_x) - 1) < 0.001
             and abs(max(e.dxf.start.y, e.dxf.end.y) - anchor.top) < 0.001]
    assert len(necks) == 2
    assert all(_is_block_template_param_entity(e, anchor) for e in necks)
