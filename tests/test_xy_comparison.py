"""Independent geometric fixtures: distances, direction and scale stay observable."""
import numpy as np
import pytest


def test_identical_paths_with_different_spacing_have_zero_geometric_error():
    from brushbot.xy_comparison.geometry import compare_paths

    result = compare_paths([[0, 0], [10, 0]], [[0, 0], [1, 0], [10, 0]], samples=101)
    assert result['metrics']['bidirectional_mean_distance_mm'] == pytest.approx(0, abs=1e-12)
    assert result['metrics']['ordered_mean_distance_mm'] == pytest.approx(0, abs=1e-12)
    assert result['metrics']['length_ratio'] == pytest.approx(1)


def test_parallel_offset_is_measured_in_mm_without_fitting_it_away():
    from brushbot.xy_comparison.geometry import compare_paths

    result = compare_paths([[0, 0], [10, 0]], [[0, 3], [10, 3]], samples=101)
    for key in ['bidirectional_mean_distance_mm', 'bidirectional_p95_distance_mm',
                'ordered_mean_distance_mm', 'start_error_mm', 'end_error_mm']:
        assert result['metrics'][key] == pytest.approx(3)
    assert result['metrics']['length_error_mm'] == pytest.approx(0)


def test_reversal_is_not_hidden_by_nearest_distance_or_automatic_reordering():
    from brushbot.xy_comparison.geometry import compare_paths

    result = compare_paths([[0, 0], [10, 0]], [[10, 0], [0, 0]], samples=101)
    assert result['metrics']['bidirectional_mean_distance_mm'] == pytest.approx(0)
    assert result['metrics']['start_error_mm'] == pytest.approx(10)
    assert result['metrics']['end_error_mm'] == pytest.approx(10)
    assert result['metrics']['ordered_mean_distance_mm'] > 5
    assert result['candidate_xy_mm'][0] == pytest.approx([10, 0])


def test_retracing_is_visible_in_length_and_order_even_when_locus_matches():
    from brushbot.xy_comparison.geometry import compare_paths

    result = compare_paths([[0, 0], [10, 0]], [[0, 0], [10, 0], [0, 0], [10, 0]])
    assert result['metrics']['bidirectional_mean_distance_mm'] == pytest.approx(0, abs=1e-12)
    assert result['metrics']['length_ratio'] == pytest.approx(3)
    assert result['metrics']['ordered_mean_distance_mm'] > 2


def test_sampling_uses_distance_and_preserves_endpoints_and_corners():
    from brushbot.xy_comparison.geometry import resample_path, compare_paths

    sampled = resample_path([[0, 0], [0, 0], [3, 0], [3, 4]], samples=8)
    assert sampled == pytest.approx(np.array([[0, 0], [1, 0], [2, 0], [3, 0],
                                              [3, 1], [3, 2], [3, 3], [3, 4]]))
    assert compare_paths([[0, 0], [3, 0], [3, 4]], sampled)['metrics'][
        'reference_length_mm'] == pytest.approx(7)


@pytest.mark.parametrize('path', [[], [[0, 0]], [[0, 0], [0, 0]],
                                 [[0, 0], [float('nan'), 1]], [[0], [1]]])
def test_invalid_or_zero_length_geometry_is_rejected(path):
    from brushbot.xy_comparison.geometry import compare_paths

    with pytest.raises(ValueError):
        compare_paths([[0, 0], [10, 0]], path)


@pytest.mark.parametrize('samples', [1, 0, 10001, True, 10.5])
def test_sampling_budget_is_bounded(samples):
    from brushbot.xy_comparison.geometry import compare_paths

    with pytest.raises(ValueError):
        compare_paths([[0, 0], [10, 0]], [[0, 0], [10, 0]], samples=samples)


def test_sparse_sampling_cannot_hide_a_large_original_vertex_excursion():
    from brushbot.xy_comparison.geometry import compare_paths

    result = compare_paths([[0, 0], [30, 0]], [[0, 0], [15, 100], [30, 0]], samples=2)
    assert result['metrics']['vertex_max_distance_mm'] == pytest.approx(100)
    assert np.max(result['candidate_vertices_mm'][:, 1]) == 100


def test_overlay_draws_original_vertices_and_bounds_even_with_two_metric_samples(tmp_path, monkeypatch):
    from matplotlib.figure import Figure
    from brushbot.xy_comparison.geometry import compare_paths
    from brushbot.xy_comparison.report import _draw_overview

    figures = []
    monkeypatch.setattr(Figure, 'savefig', lambda self, *a, **kw: figures.append(self))
    ref = dict(xy_mm=np.array([[0., 0.], [30., 0.]]), image=np.full((21, 41, 3), 255, dtype=np.uint8),
               metadata={'transform': dict(origin_px=[5, 10], origin_mm=[0, 0], rotation_deg=0, mm_per_pixel=1)})
    result = compare_paths(ref['xy_mm'], [[0, 0], [15, 100], [30, 0]], samples=2)
    _draw_overview(ref, [{'label': 'excursion'}], [result], tmp_path/'figure.png')
    overlay = figures[0].axes[2]
    line = next(line for line in overlay.lines if line.get_label() == 'excursion')
    assert max(line.get_ydata()) == 100
    assert overlay.get_ylim()[1] > 100
