"""Build the "new interface" map sheets from the TI-Reborn 2.0 HD art.

Each HD sheet in the Godot project (game/assets/hd, listed in hd_index.json)
holds new art only for the frames it lists, at ``scale`` times the native size.
The legacy renderer addresses frames in native pixels, so every listed frame is
reduced to its native rectangle (premultiplied alpha) and replaces that
rectangle of the current client sheet. Unlisted frames keep the client art.

Output: OUT/base/hd/setting/<rel>.hd (PNG data). The launcher adapter
(tools/build_native_hd_map_textures.py) loads these only in the new interface.

Usage: python tools/build_hd_map_textures.py GODOT_ASSETS CLIENT_ROOT OUT
       python tools/build_hd_map_textures.py GODOT_ASSETS CLIENT_ROOT OUT --double-density-pilot
       python tools/build_hd_map_textures.py GODOT_ASSETS CLIENT_ROOT OUT --double-density-reservation
       python tools/build_hd_map_textures.py GODOT_ASSETS CLIENT_ROOT OUT --double-density-map-list PATHS_JSON
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import sys
import zlib

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.build_visual_asset_catalog import decode  # noqa: E402
from tools.reservation_texture_ground import ground_double_density  # noqa: E402

HD_PREFIX = 'base/hd/'
HD_SUFFIX = '.hd'
HD2_SUFFIX = '.2x.hd'
HD2_CHUNK = b'tiOs'
PNG_IHDR_END = 33
MAX_NATIVE_SIDE = 2048
PILOT_SHEETS = (
    'base/setting/military/fence/concrete_wall_corner.png',
    'base/setting/military/steel_box_01b.png',
)
RESERVATION_PREFIX = 'base/setting/reservation_v2/'
RESERVATION_GROUND = {
    RESERVATION_PREFIX + f'rvound_{biome}_base_{variant}.tga': f'ground_{biome}_base_{variant}.png'
    for biome in ('military', 'village') for variant in ('a', 'b')
}


def hd_path(original: str, *, output_scale: int = 1) -> str:
    """Manifest path of the HD copy for a client sheet path."""
    path = PurePosixPath(original)
    if path.parts[:2] != ('base', 'setting') or '..' in path.parts:
        raise ValueError(f'Not a client setting sheet: {original}')
    return HD_PREFIX + '/'.join(path.parts[1:]) + {1: HD_SUFFIX, 2: HD2_SUFFIX}[output_scale]


def _reduce(tile: Image.Image, size: tuple[int, int]) -> Image.Image:
    # Premultiplied resampling: transparent pixels must not bleed their colour.
    premultiplied = tile.convert('RGBa').resize(size, Image.Resampling.LANCZOS)
    return premultiplied.convert('RGBA')


def compose(original: Image.Image, hd: Image.Image, frames: list[list[int]], scale: int,
            *, output_scale: int = 1) -> Image.Image:
    if original.mode != 'RGBA' or hd.mode != 'RGBA':
        raise ValueError('RGBA images required')
    if hd.size != (original.width * scale, original.height * scale):
        raise ValueError(f'HD sheet {hd.size} is not {scale}x the native {original.size}')
    if output_scale not in (1, 2) or output_scale > scale:
        raise ValueError(f'Unsupported output scale {output_scale} for {scale}x source')
    result = original.copy() if output_scale == 1 else original.resize(
        (original.width * output_scale, original.height * output_scale), Image.Resampling.NEAREST)
    for x, y, w, h in frames:
        # Some client frames reach past the sheet edge; the client never draws
        # the missing part, so only the part inside the sheet is replaced.
        right, bottom = min(x + w, original.width), min(y + h, original.height)
        if x < 0 or y < 0 or w <= 0 or h <= 0 or right <= x or bottom <= y:
            continue
        tile = hd.crop((x * scale, y * scale, right * scale, bottom * scale))
        size = ((right - x) * output_scale, (bottom - y) * output_scale)
        if tile.size != size:
            tile = _reduce(tile, size)
        result.paste(tile, (x * output_scale, y * output_scale))
    return result


def png_bytes(image: Image.Image, *, output_scale: int = 1) -> bytes:
    stream = io.BytesIO()
    image.save(stream, 'PNG', optimize=True)
    raw = stream.getvalue()
    if output_scale != 2:
        return raw
    # The released loader checks directly after IHDR, before optional chunks such as iCCP.
    marker = bytes(4) + HD2_CHUNK + zlib.crc32(HD2_CHUNK).to_bytes(4, 'big')
    return raw[:PNG_IHDR_END] + marker + raw[PNG_IHDR_END:]


def build(godot_assets: Path, client: Path, out: Path, *, double_density_pilot: bool = False,
          double_density_reservation: bool = False, selected_map_paths: list[str] | None = None) -> list[dict]:
    density_options = (double_density_pilot, double_density_reservation, selected_map_paths is not None)
    if sum(density_options) > 1:
        raise ValueError('Select one double-density build')
    index = json.loads((godot_assets/'hd/hd_index.json').read_text(encoding='utf-8'))
    paths = PILOT_SHEETS if double_density_pilot else sorted(index)
    if double_density_reservation:
        paths = sorted(set(RESERVATION_GROUND) | {name for name in index if name.startswith(RESERVATION_PREFIX)})
    if selected_map_paths is not None:
        if (not selected_map_paths or len(set(selected_map_paths)) != len(selected_map_paths)
                or not set(selected_map_paths) <= index.keys()):
            raise ValueError('Expected unique map sheets from the HD index')
        paths = sorted(selected_map_paths)
    output_scale = 2 if any(density_options) else 1
    records = []
    for original_path in paths:
        output_path = hd_path(original_path, output_scale=output_scale)
        source = client/original_path
        raw = source.read_bytes()
        original, codec = decode(raw)
        if max(original.size) * output_scale > MAX_NATIVE_SIDE:
            raise ValueError(f'{original_path}: output sheet exceeds {MAX_NATIVE_SIDE}px')
        if double_density_reservation and original_path in RESERVATION_GROUND and original_path not in index:
            master = ROOT/'assets/reservation-textures-v2/generated'/RESERVATION_GROUND[original_path]
            with Image.open(master) as hd:
                sheet = ground_double_density(original, hd.convert('RGBA'))
            frame_count = 2
        else:
            entry = index[original_path]
            with Image.open(godot_assets/'hd'/original_path) as hd:
                sheet = compose(original, hd.convert('RGBA'), entry['frames'], int(entry['scale']),
                                output_scale=output_scale)
            frame_count = len(entry['frames'])
        data = png_bytes(sheet, output_scale=output_scale)
        target = out/output_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        records.append(dict(path=output_path, source=original_path, source_codec=codec,
                            source_sha256=hashlib.sha256(raw).hexdigest(), size=list(sheet.size),
                            frames=frame_count, sha256=hashlib.sha256(data).hexdigest(),
                            bytes=len(data)))
    return records


if __name__ == '__main__':
    options = sys.argv[4:]
    selected = len(options) == 2 and options[0] == '--double-density-map-list'
    if len(sys.argv) < 4 or (not selected and options not in ([], ['--double-density-pilot'], ['--double-density-reservation'])):
        raise SystemExit(__doc__)
    godot, client, out = (Path(p).resolve() for p in sys.argv[1:4])
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f'Output directory is not empty: {out}')
    result = build(godot, client, out, double_density_pilot=options == ['--double-density-pilot'],
                   double_density_reservation=options == ['--double-density-reservation'],
                   selected_map_paths=json.loads(Path(options[1]).read_text(encoding='utf-8')) if selected else None)
    (out/'hd-map-textures.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(f'Built {len(result)} HD map sheets, {sum(r["bytes"] for r in result)} bytes')
