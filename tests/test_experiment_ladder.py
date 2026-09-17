import pytest

from brushbot.experiments.config import validate_experiment


def ladder_spec(**overrides):
    spec = {
        "version": 1,
        "name": "z_ladder_x",
        "path": {
            "kind": "ladder",
            "axis": "+x",
            "travel_mm": 100.0,
            "depth_from_mm": 0.0,
            "depth_to_mm": 20.0,
            "steps": 8,
            "order": "down_then_up",
            "transit_z_mm": 50.0,
        },
        "motion": {"speed_mm_s": 10.0, "accel_mm_s2": None},
        "control": {"enabled": False},
    }
    spec.update(overrides)
    return spec


def test_ladder_spec_without_z_block_is_valid():
    checked = validate_experiment(ladder_spec())
    assert checked["path"]["kind"] == "ladder"
    assert checked["path"]["steps"] == 8


def test_ladder_spec_rejects_z_block():
    spec = ladder_spec()
    spec["z"] = {"start_tcp_z_mm": 40.0, "end_tcp_z_mm": 20.0}
    with pytest.raises(ValueError, match="unknown field z"):
        validate_experiment(spec)


def test_line_spec_still_requires_z_block():
    spec = ladder_spec()
    spec["path"] = {"kind": "line", "delta_xy_mm": [10.0, 0.0]}
    with pytest.raises(ValueError, match="missing z"):
        validate_experiment(spec)


@pytest.mark.parametrize("axis", ["+x", "-x", "+y", "-y"])
def test_ladder_accepts_four_axes(axis):
    spec = ladder_spec()
    spec["path"]["axis"] = axis
    assert validate_experiment(spec)["path"]["axis"] == axis


def test_ladder_rejects_unknown_axis():
    spec = ladder_spec()
    spec["path"]["axis"] = "diagonal"
    with pytest.raises(ValueError, match="axis must be one of"):
        validate_experiment(spec)


def test_ladder_rejects_depth_from_above_depth_to():
    spec = ladder_spec()
    spec["path"]["depth_from_mm"] = 20.0
    spec["path"]["depth_to_mm"] = 0.0
    with pytest.raises(ValueError, match="depth_from_mm must be below depth_to_mm"):
        validate_experiment(spec)


def test_ladder_rejects_single_step():
    spec = ladder_spec()
    spec["path"]["steps"] = 1
    with pytest.raises(ValueError, match="steps must be an integer >= 2"):
        validate_experiment(spec)


def test_ladder_rejects_unknown_order():
    spec = ladder_spec()
    spec["path"]["order"] = "up_then_down"
    with pytest.raises(ValueError, match="order must be down_then_up"):
        validate_experiment(spec)


def test_ladder_rejects_negative_depth():
    spec = ladder_spec()
    spec["path"]["depth_from_mm"] = -1.0
    with pytest.raises(ValueError, match="depth_from_mm must be >= 0"):
        validate_experiment(spec)


def test_ladder_rejects_unknown_path_field():
    spec = ladder_spec()
    spec["path"]["radius_mm"] = 5.0
    with pytest.raises(ValueError, match="unknown field path.radius_mm"):
        validate_experiment(spec)