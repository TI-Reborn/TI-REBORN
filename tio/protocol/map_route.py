"""Dashed journey route for the patched global map, inside 1D packets.

The original 1D reader discards both Z fields; the road-map Silver keeps
them (deploy/client_global_map_roads.py). The first Z carries route words,
the second the journey's final location. A journey start sends a burst of
1D packets with the same position and turn: a header word with the dash
count, then one dash per packet. Old clients ignore the words.

Dashes are cut in map-image pixels, so they keep their length on screen
whatever the window size; the client only scales and draws them.
"""
from __future__ import annotations

from collections.abc import Sequence
import math

MAP_WIDTH, MAP_HEIGHT = 1819, 865
DASH, GAP = 9.0, 6.0
MAX_DASHES = 400
HEADER = 0x80000000
_REACH = 15  # A dash end is stored as a signed 5-bit offset from its start.


def image_point(point: Sequence[float]) -> tuple[float, float]:
    """World (-512..511) to map-image pixels, as the client projects the map."""
    return ((point[0] + 512) * MAP_WIDTH / 1024, (point[1] + 512) * MAP_HEIGHT / 1024)


def dashes(path: Sequence[Sequence[float]]) -> list[tuple[int, int, int, int]]:
    """Dash segments (x0, y0, x1, y1) in image pixels along a world polyline."""
    points = [image_point(p) for p in path]
    length = sum(math.dist(p, q) for p, q in zip(points, points[1:]))
    # Very long routes widen the gaps instead of losing their end.
    on, cycle = DASH, max(DASH + GAP, length / MAX_DASHES)
    out, phase = [], 0.0
    for (ax, ay), (bx, by) in zip(points, points[1:]):
        span = math.dist((ax, ay), (bx, by))
        start = 0.0
        while start < span:
            position = phase % cycle
            if position < on:
                end = min(span, start + on - position)
                t0, t1 = start / span, end / span
                dash = (round(ax + (bx - ax) * t0), round(ay + (by - ay) * t0),
                        round(ax + (bx - ax) * t1), round(ay + (by - ay) * t1))
                if dash[:2] != dash[2:]:
                    out.append(dash)
            else:
                end = min(span, start + cycle - position)
            phase += end - start
            start = end
    return out[:MAX_DASHES]


def dash_word(x0: int, y0: int, x1: int, y1: int) -> int:
    dx, dy = x1 - x0, y1 - y0
    if not (0 <= x0 < 2048 and 0 <= y0 < 1024 and -_REACH <= dx <= _REACH and -_REACH <= dy <= _REACH):
        raise ValueError('Route dash outside the map encoding')
    if dx == dy == 0:
        raise ValueError('Empty route dash')
    return x0 | y0 << 11 | (dx & 31) << 21 | (dy & 31) << 26


def route_words(path: Sequence[Sequence[float]]) -> tuple[int, ...]:
    words = tuple(dash_word(*dash) for dash in dashes(path))
    return (HEADER | len(words), *words)
