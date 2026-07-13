import pytest

from src.machine_config import load_machine_config
from src.side_view_config import SideViewTemplateConfig


def test_side_view_template_fixed_dimensions_are_constant():
    config = SideViewTemplateConfig()

    assert config.fixed_90 == pytest.approx(90.0)
    assert config.fixed_200 == pytest.approx(200.0)
    assert config.fixed_145 == pytest.approx(145.0)
    assert config.fixed_435 == pytest.approx(435.0)
    assert config.wheel_radius == pytest.approx(80.0)


@pytest.mark.parametrize(
    "machine_id",
    (
        "bed_618",
        "double_head_up_down",
        "double_head_up_up",
        "triple_single_down_up",
        "triple_single_up_up",
        "triple_double_down_up_up",
        "triple_double_up_up_up",
    ),
)
def test_every_machine_declares_a_block_side_view_recipe(machine_id):
    machine = load_machine_config(machine_id)

    assert machine.side_layout.block_side_mode in {
        "fixed_projected_height",
        "fixed_top_gap",
        "slot_base_plus_wheel_cut_in",
    }
