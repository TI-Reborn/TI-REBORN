"""Drivable routes of the global map along config/world_roads.json.

A route is a polyline of world points. Points off the network (an encounter
stop, a contract marker, a legacy saved position) join the nearest road
point by a straight leg; everything else follows the roads.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import heapq
import json
import math
from pathlib import Path

Point = tuple[float, float]
_EPSILON = 1e-6


@dataclass(frozen=True)
class _Edge:
    a: str
    b: str
    points: tuple[Point, ...]
    cumulative: tuple[float, ...]

    @property
    def length(self) -> float:
        return self.cumulative[-1]

    def partial(self, start: float, end: float) -> list[Point]:
        """Points driven from offset start to offset end, either direction."""
        inner = range(1, len(self.points) - 1)
        if end >= start:
            middle = [self.points[k] for k in inner if start < self.cumulative[k] < end]
        else:
            middle = [self.points[k] for k in reversed(inner) if end < self.cumulative[k] < start]
        return [point_along(self.points, start), *middle, point_along(self.points, end)]


@dataclass(frozen=True)
class _Attachment:
    """Where a point meets the network: edge index, offset and the road point."""
    edge: int
    offset: float
    point: Point


def _cumulative(points: Sequence[Point]) -> tuple[float, ...]:
    total, out = 0.0, [0.0]
    for p, q in zip(points, points[1:]):
        total += math.dist(p, q)
        out.append(total)
    return tuple(out)


def path_length(path: Sequence[Point]) -> float:
    return _cumulative(path)[-1]


def leg_index(path: Sequence[Point], distance: float) -> int:
    """Index of the segment path[i] -> path[i+1] being driven at this distance."""
    cumulative = _cumulative(path)
    for index in range(len(path) - 1):
        if distance < cumulative[index + 1]:
            return index
    return max(0, len(path) - 2)


def point_along(path: Sequence[Point], distance: float) -> Point:
    cumulative = _cumulative(path)
    if distance <= 0 or len(path) == 1:
        return tuple(path[0])
    for index in range(len(path) - 1):
        if distance < cumulative[index + 1]:
            (ax, ay), (bx, by) = path[index], path[index + 1]
            t = (distance - cumulative[index]) / (cumulative[index + 1] - cumulative[index])
            return (ax + (bx - ax) * t, ay + (by - ay) * t)
    return tuple(path[-1])


class RoadNetwork:
    def __init__(self, nodes: Mapping[str, Point], edges: Iterable[tuple[str, str, Sequence[Point]]]):
        self._nodes = {name: (float(x), float(y)) for name, (x, y) in nodes.items()}
        built = []
        for a, b, middle in edges:
            if a not in self._nodes or b not in self._nodes:
                raise ValueError(f'Road {a}-{b} references an unknown node')
            points = (self._nodes[a], *((float(x), float(y)) for x, y in middle), self._nodes[b])
            cumulative = _cumulative(points)
            if cumulative[-1] <= _EPSILON:
                raise ValueError(f'Road {a}-{b} has no length')
            built.append(_Edge(a, b, points, cumulative))
        self._edges = tuple(built)
        self._adjacent: dict[str, list[tuple[int, str]]] = {name: [] for name in self._nodes}
        for index, edge in enumerate(self._edges):
            self._adjacent[edge.a].append((index, edge.b))
            self._adjacent[edge.b].append((index, edge.a))

    @classmethod
    def from_json(cls, data: Mapping) -> RoadNetwork:
        return cls(data['nodes'], ((a, b, middle) for a, b, middle in data['edges']))

    def anchor(self, location: int) -> tuple[int, int] | None:
        """Parking point of a location: where its road ends."""
        point = self._nodes.get(f'L{location}')
        return None if point is None else (round(point[0]), round(point[1]))

    def _attach(self, point: Point) -> _Attachment:
        best: tuple[float, _Attachment] | None = None
        for index, edge in enumerate(self._edges):
            for k, ((ax, ay), (bx, by)) in enumerate(zip(edge.points, edge.points[1:])):
                dx, dy = bx - ax, by - ay
                span = dx * dx + dy * dy
                t = min(1.0, max(0.0, ((point[0] - ax) * dx + (point[1] - ay) * dy) / span))
                road = (ax + dx * t, ay + dy * t)
                gap = math.dist(point, road)
                if best is None or gap < best[0] - _EPSILON:
                    offset = edge.cumulative[k] + t * (edge.cumulative[k + 1] - edge.cumulative[k])
                    best = gap, _Attachment(index, offset, road)
        if best is None:
            raise ValueError('The road network is empty')
        return best[1]

    def plan(self, start: Point, goal: Point) -> tuple[Point, ...]:
        """Shortest drive from start to goal; raises ValueError if no road connects them."""
        start, goal = (tuple(start), tuple(goal))
        if math.dist(start, goal) <= _EPSILON:
            return (start,)
        source, target = self._attach(start), self._attach(goal)
        first, last = self._edges[source.edge], self._edges[target.edge]
        # Dijkstra from the start's road point; ties resolve by node name.
        distance = {first.a: source.offset, first.b: first.length - source.offset}
        previous: dict[str, tuple[str | None, list[Point]]] = {
            first.a: (None, first.partial(source.offset, 0)),
            first.b: (None, first.partial(source.offset, first.length))}
        queue = [(cost, name) for name, cost in distance.items()]
        heapq.heapify(queue)
        done: set[str] = set()
        while queue:
            cost, node = heapq.heappop(queue)
            if node in done:
                continue
            done.add(node)
            for index, other in self._adjacent[node]:
                edge = self._edges[index]
                forward = edge.a == node
                candidate = cost + edge.length
                if candidate < distance.get(other, math.inf) - _EPSILON:
                    distance[other] = candidate
                    previous[other] = (node, edge.partial(0, edge.length) if forward else edge.partial(edge.length, 0))
                    heapq.heappush(queue, (candidate, other))
        options = []
        for end, offset in ((last.a, 0.0), (last.b, last.length)):
            if end in distance:
                options.append((distance[end] + abs(target.offset - offset), end))
        if source.edge == target.edge:
            options.append((abs(target.offset - source.offset), None))
        if not options:
            raise ValueError('No road connects these map points')
        _, end = min(options, key=lambda option: (option[0], option[1] or ''))
        if end is None:
            legs = [first.partial(source.offset, target.offset)]
        else:
            legs = [last.partial(0 if end == last.a else last.length, target.offset)]
            node: str | None = end
            while node is not None:
                node, leg = previous[node]
                legs.append(leg)
            legs.reverse()
        points = [start]
        for leg in legs:
            points.extend(leg)
        points.append(goal)
        route = [points[0]]
        for point in points[1:]:
            if math.dist(point, route[-1]) > _EPSILON:
                route.append(point)
        return tuple(route)


ROADS = RoadNetwork.from_json(json.loads(
    (Path(__file__).resolve().parents[1] / 'config/world_roads.json').read_text(encoding='utf-8')))
