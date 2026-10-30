"""Geometry shared by straight travel and dashed map routes."""
from collections.abc import Sequence
import math

Point = tuple[float, float]


def _cumulative(points: Sequence[Point]) -> tuple[float, ...]:
    total, out = 0.0, [0.0]
    for p, q in zip(points, points[1:]):
        total += math.dist(p, q)
        out.append(total)
    return tuple(out)


def path_length(path: Sequence[Point]) -> float:
    return _cumulative(path)[-1]


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
