"""Check and restore the UV registration of HD equipment atlases.

The HD atlases (assets/equipment-textures-v1) were repainted by an image
generator from the original low-resolution atlases. Where the generator moved
or rescaled UV islands, the meshes sample the wrong pieces in game, while
item icons (rendered from the originals) still show the intended look.

`islands` rasterises the UV charts of every mesh bound to an atlas.
`register` finds, for each island, where the generator put it in the HD atlas
(scale + translation, normalised cross-correlation on detail) and
`rebuild` composes an HD atlas on the original layout: the original's colour
and shading (low frequencies) plus the registered HD detail (high
frequencies). An island without a convincing match keeps the upscaled original.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from tools.mdjx_mesh import read

MIN_SCORE = 0.4  # below this the HD island is a different drawing; keep the original
SCALES = tuple(float(s) for s in np.round(np.arange(0.6, 1.26, 0.02), 3))


@dataclass(frozen=True)
class Placement:
    scale: float  # HD island size / original island size
    dx: float  # HD position minus original position, in output pixels
    dy: float
    score: float  # normalised cross-correlation of the detail


def uv_mask(meshes: list[Path], size: int) -> Image.Image:
    """White where any mesh samples the atlas (UVs wrap like the D3D sampler)."""
    mask = Image.new('L', (size, size), 0)
    draw = ImageDraw.Draw(mask)
    for path in meshes:
        mesh = read(path)
        for i in range(0, len(mesh.indices), 3):
            corners = [mesh.vertices[j].uv for j in mesh.indices[i:i + 3]]
            u0, v0 = corners[0]
            # A triangle never straddles a wrap: keep its corners in one tile.
            points = [((u - np.floor(u0)) * size, (v - np.floor(v0)) * size) for u, v in corners]
            draw.polygon(points, fill=255, outline=255)
    return mask


def islands(mask: Image.Image, pad: int) -> list[np.ndarray]:
    """Connected UV charts (each as a boolean mask), grown by pad pixels."""
    # MaxFilter(1) crashes Pillow (integer division by zero), so pad 0 skips it.
    grown = np.asarray(mask.filter(ImageFilter.MaxFilter(2 * pad + 1)) if pad else mask) > 0
    labels = np.zeros(grown.shape, dtype=np.int32)
    count = 0
    for y, x in zip(*np.nonzero(grown)):
        if labels[y, x]:
            continue
        count += 1
        stack = [(y, x)]
        labels[y, x] = count
        while stack:
            cy, cx = stack.pop()
            for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                if 0 <= ny < grown.shape[0] and 0 <= nx < grown.shape[1] and grown[ny, nx] and not labels[ny, nx]:
                    labels[ny, nx] = count
                    stack.append((ny, nx))
    return [labels == k for k in range(1, count + 1)]


def grey(image: Image.Image) -> np.ndarray:
    return np.asarray(image.convert('L'), dtype=np.float64)


def gaussian(values: np.ndarray, radius: float) -> np.ndarray:
    """Separable Gaussian blur of a 2-D array (edges clamped)."""
    half = max(1, int(3 * radius))
    taps = np.exp(-0.5 * (np.arange(-half, half + 1) / radius) ** 2)
    taps /= taps.sum()
    padded = np.pad(values, half, mode='edge')
    rows = sum(w * padded[:, k:k + values.shape[1]] for k, w in enumerate(taps))
    return sum(w * rows[k:k + values.shape[0]] for k, w in enumerate(taps))


def detail(values: np.ndarray, radius: float) -> np.ndarray:
    return values - gaussian(values, radius)


def _ncc_map(image: np.ndarray, template: np.ndarray, weight: np.ndarray) -> np.ndarray:
    """Masked normalised cross-correlation of template over image at every offset (FFT)."""
    h, w = image.shape
    th, tw = template.shape
    shape = (h + th, w + tw)
    def corr(a: np.ndarray, b: np.ndarray) -> np.ndarray:
        fa = np.fft.rfft2(a, shape)
        fb = np.fft.rfft2(b[::-1, ::-1], shape)
        return np.fft.irfft2(fa * fb, shape)[th - 1:h, tw - 1:w]
    n = weight.sum()
    t = (template - (template * weight).sum() / n) * weight
    t_norm = np.sqrt((t ** 2).sum())
    sum_i = corr(image, weight)
    sum_i2 = corr(image ** 2, weight)
    var_i = np.maximum(sum_i2 - sum_i ** 2 / n, 1e-9)
    return corr(image, t) / (np.sqrt(var_i) * max(t_norm, 1e-9))


def register(original: Image.Image, hd: Image.Image, chart: np.ndarray, size: int,
             scales: tuple[float, ...] = tuple(np.round(np.arange(0.8, 1.32, 0.04), 3)),
             search: int = 0) -> Placement:
    """Best scale/translation of one island of `original` inside `hd`, both seen at `size` pixels."""
    base = detail(grey(original.resize((size, size), Image.Resampling.BICUBIC)), size / 128)
    target = detail(grey(hd.resize((size, size), Image.Resampling.LANCZOS)), size / 128)
    ys, xs = np.nonzero(chart)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    best = Placement(1.0, 0.0, 0.0, -1.0)
    for scale in scales:
        th, tw = max(4, round((y1 - y0) * scale)), max(4, round((x1 - x0) * scale))
        template = np.asarray(Image.fromarray(base[y0:y1, x0:x1].astype(np.float32), 'F').resize((tw, th), Image.Resampling.BILINEAR))
        weight = np.asarray(Image.fromarray(chart[y0:y1, x0:x1].astype(np.float32), 'F').resize((tw, th), Image.Resampling.BILINEAR)) > 0.5
        reach = search or size // 6
        cy, cx = (y0 + y1) / 2, (x0 + x1) / 2
        top, left = int(max(0, cy - th / 2 - reach)), int(max(0, cx - tw / 2 - reach))
        bottom, right = int(min(size, cy + th / 2 + reach)), int(min(size, cx + tw / 2 + reach))
        window = target[top:bottom, left:right]
        if window.shape[0] < th or window.shape[1] < tw or weight.sum() < 16:
            continue
        scores = _ncc_map(window, template, weight.astype(np.float64))
        iy, ix = np.unravel_index(np.argmax(scores), scores.shape)
        score = float(scores[iy, ix])
        if score > best.score:
            # Offset of the island centre between original and HD placement.
            hy, hx = top + iy + th / 2, left + ix + tw / 2
            best = Placement(float(scale), float(hx - cx), float(hy - cy), score)
    return best


def warp_island(hd: np.ndarray, chart: np.ndarray, place: Placement) -> np.ndarray:
    """HD pixels for the island's output pixels, sampled at the registered HD location."""
    size = chart.shape[0]
    ys, xs = np.nonzero(chart)
    cy, cx = (ys.min() + ys.max() + 1) / 2, (xs.min() + xs.max() + 1) / 2
    sy = cy + place.dy + (ys + 0.5 - cy) * place.scale - 0.5
    sx = cx + place.dx + (xs + 0.5 - cx) * place.scale - 0.5
    y0 = np.clip(np.floor(sy).astype(int), 0, size - 2)
    x0 = np.clip(np.floor(sx).astype(int), 0, size - 2)
    fy = np.clip(sy - y0, 0, 1)[:, None]
    fx = np.clip(sx - x0, 0, 1)[:, None]
    return (hd[y0, x0] * (1 - fy) * (1 - fx) + hd[y0, x0 + 1] * (1 - fy) * fx
            + hd[y0 + 1, x0] * fy * (1 - fx) + hd[y0 + 1, x0 + 1] * fy * fx)


def _blur(rgb: np.ndarray, radius: float) -> np.ndarray:
    return np.stack([gaussian(rgb[..., c], radius) for c in range(3)], -1)


def output_charts(charts: list[np.ndarray], size: int, pad: int) -> list[np.ndarray]:
    """Charts found at registration size, upscaled to `size` and grown by pad pixels.

    Padding only claims pixels no other chart owns, so the bilinear sampler
    never reads a neighbour's detail at island edges.
    """
    factor = size // charts[0].shape[0]
    owned = np.zeros((size, size), dtype=np.int32)
    for k, chart in enumerate(charts, 1):
        owned[np.kron(chart, np.ones((factor, factor), dtype=bool))] = k
    grown = owned.copy()
    for _ in range(pad):
        shifted = [np.roll(grown, d, a) for a in (0, 1) for d in (1, -1)]
        for other in shifted:
            grown = np.where(grown == 0, other, grown)
    return [grown == k for k in range(1, len(charts) + 1)]


def compose(original: Image.Image, hd: Image.Image, charts: list[np.ndarray],
            placements: list[Placement], min_score: float, size: int = 1024) -> Image.Image:
    """Original layout and colours plus registered HD detail on every convincingly matched island.

    Placements are in registration pixels (charts' own size) and are scaled to `size`.
    """
    factor = size / charts[0].shape[0]
    radius = size / original.width * 1.2  # just above the original's own resolution
    base = np.asarray(original.convert('RGB').resize((size, size), Image.Resampling.BICUBIC), dtype=np.float64)
    hd_rgb = np.asarray(hd.convert('RGB').resize((size, size), Image.Resampling.LANCZOS), dtype=np.float64)
    hd_detail = hd_rgb - _blur(hd_rgb, radius)
    out = base.copy()
    low = _blur(base, radius)
    for chart, place in zip(output_charts(charts, size, pad=round(factor * 1.5)), placements):
        if place.score < min_score:
            continue
        ys, xs = np.nonzero(chart)
        scaled = Placement(place.scale, place.dx * factor, place.dy * factor, place.score)
        out[ys, xs] = low[ys, xs] + warp_island(hd_detail, chart, scaled)
    return Image.fromarray(np.clip(np.round(out), 0, 255).astype(np.uint8), 'RGB')


def restore(original: Image.Image, hd: Image.Image, meshes: list[Path], min_score: float = MIN_SCORE,
            size: int = 1024, probe: int = 256) -> tuple[Image.Image, list[dict]]:
    """HD atlas back on the original UV layout; one report row per island."""
    charts = [c for c in islands(uv_mask(meshes, probe), 0) if c.sum() >= 4]
    placements = [register(original, hd, c, probe, scales=SCALES, search=probe // 4) for c in charts]
    image = compose(original, hd, charts, placements, min_score, size)
    rows = []
    for chart, place in zip(charts, placements):
        ys, xs = np.nonzero(chart)
        rows.append(dict(bbox=[int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1], pixels=int(chart.sum()),
                         scale=place.scale, dx=round(place.dx, 2), dy=round(place.dy, 2), ncc=round(place.score, 3),
                         hd_detail=place.score >= min_score))
    return image, rows
