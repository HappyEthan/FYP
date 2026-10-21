"""Trace all skeleton edges into unordered chains, junction regions and cycles."""
from __future__ import annotations

import numpy as np

from brushbot.image_geometry import pixel_graph


def _edge(a, b):
    return (a, b) if a < b else (b, a)


def cycle_path_ids(paths):
    """Non-bridge edges in the region multigraph, including parallel/self edges.

    Iterative Tarjan traversal avoids a recursion limit on complex skeletons.
    Cyclic routes need their original geometry to prevent RDP collapsing a ring.
    """
    adjacency = {}
    for path in paths:
        a, b, edge = path['start_node_id'], path['end_node_id'], path['id']
        adjacency.setdefault(a, []).append((b, edge))
        adjacency.setdefault(b, []).append((a, edge))
    discovered, low, parent, bridges = {}, {}, {}, set()
    for seed in adjacency:
        if seed in discovered:
            continue
        discovered[seed] = low[seed] = len(discovered)
        stack = [(seed, iter(adjacency[seed]))]
        while stack:
            node, neighbours = stack[-1]
            item = next(neighbours, None)
            if item is None:
                stack.pop()
                if node in parent:
                    previous, edge = parent[node]
                    low[previous] = min(low[previous], low[node])
                    if low[node] > discovered[previous]:
                        bridges.add(edge)
                continue
            other, edge = item
            if node in parent and edge == parent[node][1]:
                continue
            if other not in discovered:
                parent[other] = (node, edge)
                discovered[other] = low[other] = len(discovered)
                stack.append((other, iter(adjacency[other])))
            else:
                low[node] = min(low[node], discovered[other])
    return {path['id'] for path in paths}-bridges


def trace_skeleton(skeleton):
    """Trace external edges once; explicitly account for junction-internal edges.

    A junction is a region of adjacent degree>2 pixels. Chains end at that
    region's boundary rather than inventing an internal writing motion. Pure
    cycles get a deterministic anchor, and degree-zero pixels remain point nodes.
    """
    mask = np.asarray(skeleton)
    if mask.ndim != 2 or mask.dtype != np.bool_ or not mask.any() or mask.sum() > 100000:
        raise ValueError('skeleton must be a nonempty 2D boolean image with at most 100000 pixels')
    graph = pixel_graph(mask)
    component_of = {}
    components = []
    for seed in graph:
        if seed in component_of:
            continue
        component_id = f'c{len(components):04}'
        pending, members = [seed], []
        component_of[seed] = component_id
        while pending:
            node = pending.pop()
            members.append(node)
            for other, _ in graph[node]:
                if other not in component_of:
                    component_of[other] = component_id
                    pending.append(other)
        components.append(sorted(members))

    regions = []
    junction_pixels = {node for node in graph if len(graph[node]) > 2}
    remaining = set(junction_pixels)
    while remaining:
        seed = min(remaining)
        remaining.remove(seed)
        pending, region = [seed], []
        while pending:
            node = pending.pop()
            region.append(node)
            for other, _ in graph[node]:
                if other in remaining:
                    remaining.remove(other)
                    pending.append(other)
        regions.append(('junction', sorted(region)))
    regions.extend(('isolated' if not graph[node] else 'endpoint', [node])
                   for node in graph if len(graph[node]) <= 1)
    for members in components:
        if all(len(graph[node]) == 2 for node in members):
            regions.append(('cycle_anchor', [min(members)]))
    regions.sort(key=lambda item: item[1][0])
    nodes, node_region = [], {}
    for i, (kind, pixels) in enumerate(regions):
        node_id = f'n{i:04}'
        values = np.asarray(pixels)
        centre = values.mean(axis=0)
        distances = np.sum((values-centre)**2, axis=1)
        representative = pixels[int(np.argmin(distances))]
        nodes.append(dict(id=node_id, kind=kind, component_id=component_of[pixels[0]],
                          representative_yx=list(representative), region_pixels=[list(p) for p in pixels]))
        for pixel in pixels:
            node_region[pixel] = node_id

    all_edges = {_edge(node, other) for node, neighbours in graph.items() for other, _ in neighbours}
    internal = {edge for edge in all_edges if edge[0] in node_region and edge[1] in node_region
                and node_region[edge[0]] == node_region[edge[1]]}
    visited = set(internal)
    paths = []
    for start in sorted(node_region):
        for other, _ in graph[start]:
            if _edge(start, other) in visited:
                continue
            route = [start, other]
            visited.add(_edge(start, other))
            previous, current = start, other
            while current not in node_region:
                neighbours = [p for p, _ in graph[current] if p != previous]
                if len(neighbours) != 1:
                    raise RuntimeError('unclassified skeleton junction')
                following = neighbours[0]
                edge = _edge(current, following)
                if edge in visited:
                    raise RuntimeError('skeleton chain revisited before reaching a node')
                visited.add(edge)
                route.append(following)
                previous, current = current, following
            paths.append(dict(id=f'p{len(paths):04}', component_id=component_of[start],
                              start_node_id=node_region[start], end_node_id=node_region[current],
                              closed=route[0] == route[-1], pixels_yx=np.asarray(route, int)))
    coverage = dict(total_edges=len(all_edges), traced_edges=len(visited)-len(internal),
                    junction_internal_edges=len(internal), untraced_edges=len(all_edges-visited))
    if coverage['untraced_edges']:
        raise RuntimeError('untraced skeleton edges remain')
    return dict(nodes=nodes, paths=paths, component_count=len(components),
                skeleton_pixels=len(graph), coverage=coverage)
