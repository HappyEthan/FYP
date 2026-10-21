import copy
import json

import numpy as np
import pytest


def line_recipe():
    return {
        "schema_version": 1,
        "id": "heng",
        "name": "横",
        "description": "Editable synthetic reference stroke",
        "reference": "中字工程试验；不是实测磁目标",
        "placement": {"origin_mm": [140., 0.], "rotation_deg": 180., "scale": 1.},
        "path": {"kind": "rounded_polyline", "points_mm": [[-50., 0.], [50., 0.]],
                 "corner_radius_mm": 2.},
        "magnetic_target": {"interpolation": "quintic", "knots_s_uT":
                            [[0., 100.], [.5, 200.], [1., 120.]]},
        "timing": {"speed_mm_s": 10., "accel_mm_s2": 30.,
                   "angular_speed_deg_s": 20., "angular_accel_deg_s2": 40.},
        "orientation": {"kind": "tangent_tilt", "tilt_deg": 15.,
                        "smoothing_mm": 1.},
        "filter_definition": {"kind": "ema", "alpha": .3},
    }


def test_recipe_changes_geometry_targets_and_speed_without_editing_python():
    from scripts.generate_strokeplan_from_json import build_plan

    recipe = line_recipe()
    first = build_plan(recipe).strokes[0]
    # Drawing right maps to -X, while length is mm in JSON and m in V3.
    assert first.xy[[0, -1]] == pytest.approx(np.array([[.190, 0.], [.090, 0.]]))
    assert first.g_target[[0, -1]] == pytest.approx([100., 120.])
    assert np.interp(.5, first.s, first.g_target) == pytest.approx(200., abs=.001)
    assert np.max(np.linalg.norm(np.diff(first.xy, axis=0), axis=1) / np.diff(first.t)) <= .010001
    assert first.orientation[0] == pytest.approx([0., -np.deg2rad(15.), 0.], abs=1e-12)

    recipe["path"]["points_mm"][-1][0] = 70.
    recipe["magnetic_target"]["knots_s_uT"][1][1] = 230.
    recipe["timing"]["speed_mm_s"] = 5.
    second = build_plan(recipe).strokes[0]
    assert second.xy[-1] == pytest.approx([.070, 0.])
    assert np.interp(.5, second.s, second.g_target) == pytest.approx(230., abs=.001)
    assert second.t[-1] > first.t[-1] * 1.8
    assert np.max(np.linalg.norm(np.diff(second.xy, axis=0), axis=1) / np.diff(second.t)) <= .005001


def test_curved_stroke_preserves_bezier_endpoints_and_tangent_pose():
    from scripts.generate_strokeplan_from_json import build_plan

    recipe = line_recipe()
    recipe["path"] = {"kind": "cubic_bezier", "points_mm":
                      [[30., 50.], [30., 10.], [0., -20.], [-40., -50.]]}
    plan = build_plan(recipe)
    stroke = plan.strokes[0]
    assert stroke.xy[[0, -1]] == pytest.approx(np.array([[.110, -.050], [.180, .050]]))
    assert np.ptp(stroke.orientation[:, 0]) > .05
    assert np.all(np.diff(stroke.t) > 0)
    assert np.allclose(stroke.t / .02, np.round(stroke.t / .02))
    plan.validate()


def test_speed_controls_slow_down_the_requested_part_of_the_path():
    from scripts.generate_strokeplan_from_json import build_plan

    recipe = line_recipe()
    recipe["timing"]["speed_knots_s_mm_s"] = [[0., 10.], [.3, 10.], [.4, 2.], [.6, 2.], [.7, 10.], [1., 10.]]
    stroke = build_plan(recipe).strokes[0]
    speed = np.linalg.norm(np.diff(stroke.xy, axis=0), axis=1) / np.diff(stroke.t) * 1000
    mid = (stroke.s[:-1] > .42) & (stroke.s[1:] < .58)
    assert np.max(speed[mid]) <= 2.001
    assert np.max(speed[stroke.s[1:] < .25]) > 8.


@pytest.mark.parametrize("change, message", [
    (lambda r: r["magnetic_target"].update(knots_s_uT=[[.1, 100.], [1., 120.]]), "0.*1"),
    (lambda r: r["magnetic_target"].update(knots_s_uT=[[0., 100.], [.5, 200.], [.5, 190.], [1., 120.]]), "increas"),
    (lambda r: r["path"].update(points_mm=[[0., 0.], [0., 0.]]), "duplicate|length"),
    (lambda r: r["timing"].update(speed_mm_s=-1.), "positive"),
    (lambda r: r["placement"].update(scale=float("nan")), "finite"),
    (lambda r: r["magnetic_target"].update(interpolation="spline"), "interpolation"),
    (lambda r: r["timing"].update(speed_mm_ss=7.), "unknown"),
    (lambda r: r.update(z_cmd_mm=30.), "unknown|Z"),
    (lambda r: r.update(schema_version=2), "schema_version"),
])
def test_invalid_recipe_is_rejected_instead_of_silently_ignored(change, message):
    from scripts.generate_strokeplan_from_json import build_plan

    recipe = line_recipe()
    change(recipe)
    with pytest.raises(ValueError, match=message):
        build_plan(recipe)


def test_export_freezes_recipe_and_round_trips_v3_without_overwriting(tmp_path):
    from scripts.generate_strokeplan_from_json import generate
    from brushbot.target_strokeplan import StrokePlan

    recipe_path = tmp_path / "heng.json"
    original = line_recipe()
    recipe_path.write_text(json.dumps(original), encoding="utf-8")
    output = tmp_path / "plans"
    report = generate([recipe_path], output, preview=False)
    plan = StrokePlan.load(output / "heng" / "strokeplan.npz")
    assert len(plan.strokes) == 1
    assert plan.meta["source"] == "synthetic"
    assert plan.meta["recipe_sha256"]
    assert json.loads((output / "heng" / "recipe.json").read_text()) == original
    assert report["strokes"][0]["name"] == "横"
    with pytest.raises(FileExistsError):
        generate([recipe_path], output, preview=False)
    # Editing the source must not change an already exported target or its snapshot.
    edited = copy.deepcopy(original)
    edited["magnetic_target"]["knots_s_uT"][1][1] = 250.
    recipe_path.write_text(json.dumps(edited), encoding="utf-8")
    assert StrokePlan.load(output / "heng" / "strokeplan.npz").strokes[0].g_target.max() <= 200.001


def test_invalid_later_recipe_creates_no_partial_output(tmp_path):
    from scripts.generate_strokeplan_from_json import generate

    good, bad = tmp_path / "heng.json", tmp_path / "shu.json"
    good.write_text(json.dumps(line_recipe()), encoding="utf-8")
    invalid = line_recipe()
    invalid["id"] = "../escape"
    bad.write_text(json.dumps(invalid), encoding="utf-8")
    output = tmp_path / "plans"
    with pytest.raises(ValueError, match="id"):
        generate([good, bad], output, preview=False)
    assert not output.exists()


def test_default_retiming_keeps_existing_zhong_behavior():
    from scripts.generate_directional_character_trial import directional_stroke
    from brushbot.target_strokeplan import Stroke

    xy = np.column_stack([np.linspace(0., .1, 101), np.zeros(101)])
    source = Stroke(np.linspace(0., 1., 101), xy, np.linspace(0., 10., 101), np.full(101, 160.))
    original = directional_stroke(source)
    configured = directional_stroke(source, speed_mm_s=10., tilt_deg=15., accel_mm_s2=30.,
                                   angular_speed_deg_s=20., angular_accel_deg_s2=40., smoothing_mm=1.)
    for field in ("xy", "t", "g_target", "orientation"):
        assert np.array_equal(getattr(original, field), getattr(configured, field))
