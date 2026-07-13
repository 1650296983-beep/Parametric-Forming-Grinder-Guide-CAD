from dataclasses import replace

import pytest

from src.geometry import build_tile_section
from src.spec_parser import parse_company_tile_spec
from src.validator import validate_profile, validate_tile_section


def test_validator_passes_first_company_spec():
    spec = parse_company_tile_spec("R17.45*R15.8*6.20(-0.02/-0.04)*15.5*1.65")
    tile_section = build_tile_section(spec)
    result = validate_tile_section(tile_section)

    assert result.ok, result.errors
    assert result.finished.ok
    assert result.forming.ok


def test_validator_checks_chord_width_radius_closure_and_nonzero_segments():
    spec = parse_company_tile_spec("R17.45*R15.8*6.20(-0.02/-0.04)*15.5*1.65")
    profile = build_tile_section(spec).finished_profile
    result = validate_profile(profile)

    assert result.ok
    outer_arc = profile.segments[0]
    right_side = profile.segments[1]
    inner_arc = profile.segments[2]
    left_side = profile.segments[3]

    assert outer_arc.radius == pytest.approx(spec.R_outer)
    assert inner_arc.radius == pytest.approx(spec.R_inner)
    assert outer_arc.start.distance_to(outer_arc.end) == pytest.approx(spec.chord_width)
    assert inner_arc.start.distance_to(inner_arc.end) == pytest.approx(spec.chord_width)
    assert right_side.length > 0.001
    assert left_side.length > 0.001

    for index, current in enumerate(profile.segments):
        following = profile.segments[(index + 1) % len(profile.segments)]
        assert current.end.distance_to(following.start) < 0.001


def test_validator_reports_bad_thickness_on_manual_profile():
    spec = parse_company_tile_spec("R17.45*R15.8*6.20(-0.02/-0.04)*15.5*1.65")
    profile = build_tile_section(spec).finished_profile
    profile = replace(profile, params=replace(profile.params, thickness=1.60))

    result = validate_profile(profile)
    assert not result.ok
    assert any("thickness" in error for error in result.errors)


def test_validator_checks_forming_profile_same_r_and_thickness_gap():
    spec = parse_company_tile_spec("R17.45*R15.8*6.20(-0.02/-0.04)*15.5*1.65")
    forming = build_tile_section(spec).forming_profile
    result = validate_profile(forming)

    assert result.ok, result.errors
    assert forming.params.R_outer == pytest.approx(forming.params.R_inner)
    assert forming.segments[1].length == pytest.approx(spec.thickness)
    assert forming.segments[3].length == pytest.approx(spec.thickness)
