"""Hand-drawn graph fixtures validate all edges, loops and disconnected parts."""
import numpy as np


def skeleton(points, shape=(15, 15)):
    mask = np.zeros(shape, dtype=bool)
    for y, x in points:
        mask[y, x] = True
    return mask


def test_line_graph_has_one_path_and_two_endpoints():
    from brushbot.character_xy.topology import trace_skeleton

    result = trace_skeleton(skeleton([(7, x) for x in range(2, 13)]))
    assert len(result['paths']) == 1
    assert [n['kind'] for n in result['nodes']] == ['endpoint', 'endpoint']
    assert result['paths'][0]['pixels_yx'][[0, -1]].tolist() == [[7, 2], [7, 12]]
    assert result['coverage'] == dict(total_edges=10, traced_edges=10, junction_internal_edges=0, untraced_edges=0)


def test_cross_is_four_segments_at_one_junction_not_two_invented_strokes():
    from brushbot.character_xy.topology import trace_skeleton

    mask = skeleton([(7, x) for x in range(2, 13)]+[(y, 7) for y in range(2, 13)])
    result = trace_skeleton(mask)
    assert len(result['paths']) == 4
    assert sum(n['kind'] == 'junction' for n in result['nodes']) == 1
    assert sum(n['kind'] == 'endpoint' for n in result['nodes']) == 4
    assert result['coverage']['traced_edges'] == 20
    assert result['coverage']['untraced_edges'] == 0


def test_closed_cycle_is_preserved_with_a_deterministic_anchor():
    from brushbot.character_xy.topology import trace_skeleton

    points = ([(2, x) for x in range(2, 13)]+[(12, x) for x in range(2, 13)]
              +[(y, 2) for y in range(3, 12)]+[(y, 12) for y in range(3, 12)])
    result = trace_skeleton(skeleton(points))
    assert len(result['paths']) == 1
    path = result['paths'][0]
    assert path['closed'] is True
    assert path['start_node_id'] == path['end_node_id']
    assert path['pixels_yx'][0].tolist() == path['pixels_yx'][-1].tolist() == [2, 2]
    assert result['coverage']['traced_edges'] == 40
    assert result['coverage']['untraced_edges'] == 0


def test_disconnected_paths_and_isolated_point_are_all_retained():
    from brushbot.character_xy.topology import trace_skeleton

    mask = skeleton([(2, x) for x in range(2, 7)]+[(10, x) for x in range(8, 13)]+[(6, 6)])
    result = trace_skeleton(mask)
    assert result['component_count'] == 3
    assert len(result['paths']) == 2
    assert sum(n['kind'] == 'isolated' for n in result['nodes']) == 1
    assert result['coverage']['untraced_edges'] == 0


def test_adjacent_junctions_are_grouped_and_internal_edges_are_accounted_for():
    from brushbot.character_xy.topology import trace_skeleton

    points = [(7, x) for x in range(2, 13)]+[(y, 6) for y in range(2, 8)]+[(y, 7) for y in range(7, 13)]
    result = trace_skeleton(skeleton(points))
    junctions = [n for n in result['nodes'] if n['kind'] == 'junction']
    assert len(junctions) == 1
    assert junctions[0]['region_pixels'] == [[7, 6], [7, 7]]
    assert result['coverage']['junction_internal_edges'] == 1
    assert len(result['paths']) == 4
    assert result['coverage']['total_edges'] == result['coverage']['traced_edges']+1


def test_trace_order_and_ids_are_repeatable():
    from brushbot.character_xy.topology import trace_skeleton

    mask = skeleton([(7, x) for x in range(2, 13)]+[(y, 7) for y in range(2, 8)])
    first, second = trace_skeleton(mask), trace_skeleton(mask.copy())
    assert [p['id'] for p in first['paths']] == [p['id'] for p in second['paths']]
    assert [n['id'] for n in first['nodes']] == [n['id'] for n in second['nodes']]
    for a, b in zip(first['paths'], second['paths']):
        np.testing.assert_array_equal(a['pixels_yx'], b['pixels_yx'])


def test_shared_primitives_keep_thick_stroke_components_and_diagonal_connections():
    from brushbot.image_geometry import connected_components, thin_mask, pixel_graph

    mask = np.zeros((30, 30), bool)
    mask[10:19, 3:26] = True
    assert len(connected_components(mask)) == 1
    thinned = thin_mask(mask)
    assert 10 < thinned.sum() < mask.sum()
    graph = pixel_graph(skeleton([(2, 2), (3, 3), (4, 4)]))
    assert [len(e) for e in graph.values()] == [1, 2, 1]
