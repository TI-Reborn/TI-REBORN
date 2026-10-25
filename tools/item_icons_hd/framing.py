"""Pure camera framing for icon renders; shared by Blender and tests.

Native models are Y-up (fighter parts stand around y=1.1..1.9). Blender is
Z-up, so (x, y, z) becomes (x, -z, y), the same mapping the existing female
fighter Blender tool uses. Each slot has a fixed orthographic view so every
icon of one kind is shot from the same angle and light.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

# yaw: rotation around the vertical axis (0 = model front faces the camera);
# pitch: camera elevation; both in degrees.
VIEWS = {
    'head': (25.0, 12.0),
    'body': (18.0, 6.0),
    'legs': (12.0, 4.0),
    'dog': (35.0, 15.0),
    'device': (30.0, 18.0),
    'weapon': (90.0, 0.0),  # side view, barrel to the right
}
MARGIN = 0.08  # fraction of the canvas kept free on each side


@dataclass(frozen=True)
class Frame:
    center: tuple[float, float, float]
    ortho_scale: float
    yaw: float
    pitch: float
    distance: float


def to_blender(point):
    x, y, z = point
    return (x, -z, y)


def bounds(points):
    if not points:
        raise ValueError('Empty geometry')
    lo = tuple(min(p[i] for p in points) for i in range(3))
    hi = tuple(max(p[i] for p in points) for i in range(3))
    return lo, hi


def projected_extent(points, yaw, pitch):
    """Width and height of the points seen by the orthographic camera."""
    cy, sy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    cp, sp = math.cos(math.radians(pitch)), math.sin(math.radians(pitch))
    us, vs = [], []
    for x, y, z in points:
        # Blender scene contract (render_blender.py): the model is rotated by
        # -yaw around Z; the camera sits at (0, -d*cos(pitch), d*sin(pitch))
        # looking at the origin, so screen right is +X and screen up is
        # (0, sin(pitch), cos(pitch)).
        u = x * cy + y * sy
        depth = -x * sy + y * cy
        v = z * cp + depth * sp
        us.append(u)
        vs.append(v)
    return max(us) - min(us), max(vs) - min(vs)


def frame(points, slot, canvas=(1024, 1024)):
    if slot not in VIEWS:
        raise ValueError(f'Unknown icon slot {slot!r}')
    if canvas[0] <= 0 or canvas[1] <= 0:
        raise ValueError('Canvas must be positive')
    world = [to_blender(p) for p in points]
    lo, hi = bounds(world)
    center = tuple((a + b) / 2 for a, b in zip(lo, hi))
    local = [tuple(p[i] - center[i] for i in range(3)) for p in world]
    yaw, pitch = VIEWS[slot]
    width, height = projected_extent(local, yaw, pitch)
    aspect = canvas[0] / canvas[1]
    usable = 1 - 2 * MARGIN
    # Blender's ortho_scale spans the larger canvas side.
    scale = max(width / usable if aspect >= 1 else width / usable / aspect,
                height / usable * aspect if aspect >= 1 else height / usable)
    radius = max(math.dist(lo, hi), 1e-3)
    return Frame(center, max(scale, 1e-3), yaw, pitch, radius * 4)
