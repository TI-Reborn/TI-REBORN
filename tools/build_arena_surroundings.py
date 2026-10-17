"""Export approved surroundings without nonlinear distortion.

Approved concepts select original city props, composited at unchanged1:1
native pixel scale. The canal variant uses original-scale approved modules.
Original city soft ground-brush frames overlap at native pixel size under
the artwork, filling gaps between scenery and the playable diamond.
Exact geometric clipping clears the existing gameplay hole. Every GPU bitmap
is a padded1024x1024 canvas with whole-frame UVs. Type1 foreground models use
inside border anchors and signed offsets, avoiding the original ground mask.
Scene cells remain1x1zero and the host appends the scene at ground origin(0,0).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image

from arena_surroundings_native import encode_scene, encode_tile

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets/arena-surroundings-v1"
MASTERS = ASSETS / "masters"
OVERLAY = ASSETS / "client-overlay"
REPORTS = ROOT / "reports/arena-surroundings-implementation"
TOWN_CODES = {"R": "rv", "D": "de", "N": "ny", "M": "mz"}
WIDTH_DEPTH = {38: 24, 57: 36}
PATCH = 1024
SIDE_NAMES = ("x_negative", "y_negative", "x_at_or_above_width", "y_at_or_above_width")
GROUND_NAMES = {
    "R": ["base/setting/village/ground_village_base_a.tga", "base/setting/village/ground_village_base_b.tga"],
    "D": ["base/setting/forest/ground_forest_base_a.tga", "base/setting/forest/ground_forest_base_b.tga"],
    "N": ["base/setting/ny/ground_ny_base_a_01.tga"],
    "M": ["base/setting/military/ground_military_base_a.tga", "base/setting/military/ground_military_base_b.tga"],
}


def original_ground(town: str) -> tuple[list[tuple[Image.Image, dict]], dict]:
    """Use hash-verified original pixels and source TILE frame/pattern/shift."""
    reference_root = ROOT / "reports/arena-surroundings-concepts"
    records = json.loads((reference_root / "reference-proof.json").read_text(encoding="utf-8"))
    records = {r["published_path"]: r for r in records}
    manifest = json.loads((reference_root / "source/current-client-manifest.json").read_text(encoding="utf-8"))
    manifest_files = {r["path"]: r for r in manifest["files"]}
    frames, sources, decoded_images = [], [], {}
    for name in GROUND_NAMES[town]:
        record = records[name]
        source_path, decoded_path = reference_root / "source" / name, Path(record["decoded_path"])
        assert sha(source_path.read_bytes()) == record["sha256"] == manifest_files[name]["sha256"]
        with Image.open(source_path) as image:
            original = image.convert("RGBA")
        with Image.open(decoded_path) as image:
            decoded = image.convert("RGBA")
        assert original.size == decoded.size == (512, 512)
        assert original.tobytes() == decoded.tobytes(), "Decoded reference pixels differ from original ground"
        decoded_images[name] = original
        sources.append({"published_path": name, "source_sha256": record["sha256"],
                        "decoded_reference": decoded_path.relative_to(ROOT).as_posix(),
                        "decoded_sha256": sha(decoded_path.read_bytes())})
    directory = Path(GROUND_NAMES[town][0]).parent
    setting_root = Path(r"C:/Program Files (x86)/TIOnline")
    town_name = {"R": "village", "D": "forest", "N": "ny", "M": "military"}[town]
    sprites = []
    for index in range(1, 3 if town == "N" else 5):
        model_name = (directory / f"ground_{town_name}_{index}.t").as_posix()
        raw = (setting_root / model_name).read_bytes()
        assert sha(raw) == manifest_files[model_name]["sha256"]
        # The original v0/v2 ground files share this numeric record prefix.
        assert raw[:8] == b"TI TILE\0" and raw[10] in (0, 2)
        assert struct.unpack_from("<H", raw, 8)[0] == 1 and raw[68:70] == b"\0\0"
        world_x, world_y = struct.unpack_from("<ii", raw, 28)
        shift_x, shift_y = struct.unpack_from("<hh", raw, 48)
        frame_width, frame_height = struct.unpack_from("<HH", raw, 60)
        pattern = raw[64]
        texture_name = raw[204:204 + raw[203]].decode("ascii")
        texture_path = (directory / texture_name).as_posix()
        original = decoded_images[texture_path]
        columns = original.width // frame_width
        px, py = (pattern % columns) * frame_width, (pattern // columns) * frame_height
        crop = (px, py, px + frame_width, py + frame_height)
        assert crop[2] <= original.width and crop[3] <= original.height
        frame = original.crop(crop)
        a = np.asarray(frame.getchannel("A"))
        assert a[0, 0] == a[0, -1] == 0 and np.any(a >= 128)
        sprite = {"published_model_path": model_name, "model_sha256": sha(raw),
                  "original_model_version": raw[10], "texture_path": texture_path,
                  "source_crop": list(crop), "frame_dimensions": [frame_width, frame_height],
                  "pattern_index": pattern, "native_world_xy": [world_x, world_y],
                  "native_screen_shift": [shift_x, shift_y], "rgba_pixel_sha256": sha(frame.tobytes())}
        frames.append((frame, sprite))
        sprites.append(sprite)
    return frames, {"method": "Overlap unchanged original ground-brush frames at4x4 world-cell intervals, honoring native frame/pattern/XYshift",
                    "native_pixel_dimensions": sorted({tuple(m["frame_dimensions"]) for m in sprites}),
                    "sprites": sprites, "native_world_chunk_cells": 8,
                    "rescaling": False, "nonlinear_transform": False,
                    "manifest_version": manifest["version"], "sources": sources}


def ground_underlay(width: int, depth: int, town: str) -> tuple[Image.Image, dict]:
    """Composite original diamond frames at exact native pixel locations."""
    frames, metadata = original_ground(town)
    full_width, full_height = projected_bounds(width, depth)
    result = Image.new("RGBA", (full_width, full_height))
    tiles = []
    first = math.floor(-depth / 4) * 4 - 12
    last = math.ceil((width + depth) / 4) * 4 + 12
    for x in range(first, last, 4):
        for y in range(first, last, 4):
            frame_index = ((x // 4) * 7 + (y // 4) * 11) % len(frames)
            frame, sprite = frames[frame_index]
            wx, wy = x + sprite["native_world_xy"][0], y + sprite["native_world_xy"][1]
            px = 32 * (wy - wx) + sprite["native_screen_shift"][0] + full_width // 2
            py = 16 * (wx + wy) + sprite["native_screen_shift"][1] + 32 * depth
            result.alpha_composite(frame, (px, py))
            tiles.append({"world_origin": [x, y], "canvas_origin": [px, py], "frame_index": frame_index})
    metadata.update(tiles=tiles, tile_count=len(tiles), pixel_scale=[1, 1],
                    placement_stride_world_cells=[4, 4], original_frame_alpha_unchanged=True,
                    rationale="Soft native brushes overlap; no alpha hardening, RGB editing or per-axis scale")
    return result, metadata


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def recorded_source_current(record: dict, path_key: str, sha_key: str) -> bool:
    """A reused report must reference the current, contained source bytes."""
    if not record.get(path_key) or not record.get(sha_key):
        return False
    path = (ROOT / record[path_key]).resolve()
    return path.is_relative_to(ROOT) and path.is_file() and sha(path.read_bytes()) == record[sha_key]


def composition_source_current(scene: dict, palette_sha: str) -> bool:
    composition = scene.get("composition", {})
    if composition.get("palette_sha256") != palette_sha:
        return False
    if scene["master_id"] == "R3":
        return recorded_source_current(composition, "approved_source", "approved_source_sha256")
    return True


def visible_rgba_sha(image: Image.Image) -> str:
    """Hash all visible RGBA pixels with bounded temporary memory."""
    digest = hashlib.sha256()
    for top in range(0, image.height, 128):
        pixels = np.asarray(image.crop((0, top, image.width, min(image.height, top + 128))))
        digest.update(pixels[pixels[:, :, 3] != 0].tobytes())
    return digest.hexdigest()


def file_record(path: Path) -> dict:
    raw = path.read_bytes()
    return {"path": path.relative_to(OVERLAY).as_posix(), "size": len(raw), "sha256": sha(raw)}


def projected_bounds(width: int, depth: int) -> tuple[int, int]:
    full_width = (2 * width + 4 * depth) * 32
    return full_width, full_width // 2


def geometry_mask(width: int, depth: int) -> Image.Image:
    """Binary alpha mask from inverse projection at raster pixel centers."""
    full_width, full_height = projected_bounds(width, depth)
    result = np.zeros((full_height, full_width), dtype=np.uint8)
    screen_x2 = 2 * np.arange(full_width, dtype=np.int32) + 1 - full_width
    for row in range(full_height):
        screen_y2 = 2 * row + 1 - 64 * depth
        world_x128 = 2 * screen_y2 - screen_x2
        world_y128 = 2 * screen_y2 + screen_x2
        outer = ((world_x128 >= -128 * depth) & (world_x128 <= 128 * (width + depth)) &
                 (world_y128 >= -128 * depth) & (world_y128 <= 128 * (width + depth)))
        hole = ((world_x128 >= 0) & (world_x128 <= 128 * width) &
                (world_y128 >= 0) & (world_y128 <= 128 * width))
        result[row, outer & ~hole] = 255
    return Image.fromarray(result)


def validate_master(path: Path) -> dict:
    with Image.open(path) as image:
        if image.format != "PNG" or image.mode != "RGBA":
            raise ValueError(f"{path.name}: expected a PNG RGBA master")
        width, height = image.size
        if width != 2 * height:
            raise ValueError(f"{path.name}: expected exact2:1 canvas; got{width}x{height}")
        alpha = np.asarray(image.getchannel("A"))
        if not np.any(alpha == 0) or not np.any(alpha >= 128):
            raise ValueError(f"{path.name}: master must contain transparent hole and opaque painting")
        # A small central core must already be transparent. The geometric mask
        # may trim boundary registration error, but cannot legitimise an opaque master.
        core = alpha[height // 2 - max(1, height // 64):height // 2 + max(1, height // 64),
                     width // 2 - max(1, width // 64):width // 2 + max(1, width // 64)]
        central_clear = float(np.count_nonzero(core == 0) / core.size)
        if central_clear < 0.50 or int(alpha[height // 2, width // 2]) >= 128:
            raise ValueError(f"{path.name}: center core is opaque; transparent fraction={central_clear:.5f}")
        return {"path": path.relative_to(ROOT).as_posix(), "sha256": sha(path.read_bytes()),
                "dimensions": [width, height], "mode": image.mode,
                "alpha_extrema": [int(alpha.min()), int(alpha.max())],
                "central_core_transparent_fraction": central_clear,
                "registration": {"method": "Approved concept provenance; runtime uses unchanged1:1 original native city props or canal modules",
                                 "nonlinear_transform": False, "source_rgb_editing": False,
                                 "sampling": "No runtime resizing of artwork; source master stays immutable"}}


def classify_anchor(x: int, y: int, width: int) -> list[str]:
    return [name for name, hit in zip(SIDE_NAMES, (x < 0, y < 0, x >= width, y >= width)) if hit]


def inside_anchor(canvas_center, width: int, depth: int) -> tuple[int, int]:
    full_width, _ = projected_bounds(width, depth)
    sx, sy = canvas_center[0] - full_width / 2, canvas_center[1] - 32 * depth
    world_x, world_y = sy / 32 - sx / 64, sy / 32 + sx / 64
    x, y = min(width - 1, max(0, round(world_x))), min(width - 1, max(0, round(world_y)))
    if 0 < x < width - 1 and 0 < y < width - 1:
        candidates = [(0, y), (width - 1, y), (x, 0), (x, width - 1)]
        x, y = min(candidates, key=lambda p: ((p[0] - world_x) ** 2 + (p[1] - world_y) ** 2, p))
    assert 0 <= x < width and 0 <= y < width
    return x, y


def classify_patch(alpha: np.ndarray, cx: int, cy: int, width: int, depth: int) -> tuple[list[str], list[float]]:
    rows, cols = np.nonzero(alpha)
    full_width, _ = projected_bounds(width, depth)
    sx, sy = cols + cx + 0.5 - full_width / 2, rows + cy + 0.5 - 32 * depth
    wx, wy = sy / 32 - sx / 64, sy / 32 + sx / 64
    bounds = [float(wx.min()), float(wy.min()), float(wx.max()), float(wy.max())]
    sides = [name for name, hit in zip(SIDE_NAMES, (bounds[0] < 0, bounds[1] < 0, bounds[2] >= width, bounds[3] >= width)) if hit]
    assert sides, "A decorative patch has no actual pixels outside the gameplay field"
    return sides, bounds


def alpha_proof(alpha: np.ndarray, width: int, depth: int, minimum: float) -> dict:
    """Independent diamond inequality plus four exterior edge/corner bands.

    Export clipping uses inverse world bounds; hole/outside checks below use
    Manhattan distance to the common diamond center, not the export mask.
    """
    full_width, full_height = projected_bounds(width, depth)
    assert alpha.shape == (full_height, full_width)
    screen_x2 = 2 * np.arange(full_width, dtype=np.int32) + 1 - full_width
    hole_count = hole_bad = outside_count = outside_bad = 0
    counts = {name: {"pixels": 0, "opaque_pixels": 0, "nonzero_pixels": 0} for name in SIDE_NAMES}
    corner_names = ("corner_origin", "corner_x", "corner_y", "corner_opposite")
    corner_counts = {name: {"pixels": 0, "opaque_pixels": 0, "nonzero_pixels": 0} for name in corner_names}
    band = 4  # Four world cells, excluding the half-cell anti-aliased edge.
    for row in range(full_height):
        a = alpha[row]
        center_y2 = 2 * row + 1 - full_height
        diamond_distance = np.abs(screen_x2) + 2 * abs(center_y2)
        hole, outside = diamond_distance <= 64 * width, diamond_distance > full_width
        hole_count += int(np.count_nonzero(hole))
        hole_bad += int(np.count_nonzero(a[hole]))
        outside_count += int(np.count_nonzero(outside))
        outside_bad += int(np.count_nonzero(a[outside]))
        sy2 = 2 * row + 1 - 64 * depth
        wx, wy = 2 * sy2 - screen_x2, 2 * sy2 + screen_x2
        middle_x, middle_y = (wx >= 256) & (wx <= 128 * (width - 2)), (wy >= 256) & (wy <= 128 * (width - 2))
        masks = (((wx >= -128 * band) & (wx <= -64)) & middle_y,
                 ((wy >= -128 * band) & (wy <= -64)) & middle_x,
                 ((wx >= 128 * width + 64) & (wx <= 128 * (width + band))) & middle_y,
                 ((wy >= 128 * width + 64) & (wy <= 128 * (width + band))) & middle_x)
        for name, mask in zip(SIDE_NAMES, masks):
            samples = a[mask]
            counts[name]["pixels"] += len(samples)
            counts[name]["opaque_pixels"] += int(np.count_nonzero(samples >= 128))
            counts[name]["nonzero_pixels"] += int(np.count_nonzero(samples))
        negative_x, negative_y = (wx >= -128 * band) & (wx <= -64), (wy >= -128 * band) & (wy <= -64)
        positive_x = (wx >= 128 * width + 64) & (wx <= 128 * (width + band))
        positive_y = (wy >= 128 * width + 64) & (wy <= 128 * (width + band))
        corner_masks = (negative_x & negative_y, positive_x & negative_y,
                        negative_x & positive_y, positive_x & positive_y)
        for name, mask in zip(corner_names, corner_masks):
            samples = a[mask]
            corner_counts[name]["pixels"] += len(samples)
            corner_counts[name]["opaque_pixels"] += int(np.count_nonzero(samples >= 128))
            corner_counts[name]["nonzero_pixels"] += int(np.count_nonzero(samples))
    assert hole_bad == 0, f"Protective gameplay hole has{hole_bad} painted pixels"
    assert outside_bad == 0, f"Outer diamond has{outside_bad} escaping pixels"
    for name, count in list(counts.items()) + list(corner_counts.items()):
        assert count["pixels"] > 0
        count["opaque_fraction"] = count["opaque_pixels"] / count["pixels"]
        count["nonzero_fraction"] = count["nonzero_pixels"] / count["pixels"]
        assert count["opaque_fraction"] >= minimum, f"{name}: opaque coverage{count['opaque_fraction']:.4f} below{minimum}"
    return {"passed": True, "method": "Pixel-center diamond inequalities independent of inverse-world export mask",
            "hole_pixels": hole_count, "hole_nonzero_pixels": hole_bad,
            "outside_pixels": outside_count, "outside_nonzero_pixels": outside_bad,
            "edge_band_world_cells": [-band, -0.5], "edge_endpoints_excluded_cells": 2,
            "opaque_alpha_threshold": 128, "minimum_opaque_fraction": minimum,
            "four_sides": counts, "four_corners": corner_counts}


def write(path: Path, raw: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)


def build_scene(master_id: str, source: dict, width: int, minimum: float) -> dict:
    depth = WIDTH_DEPTH[width]
    full_width, full_height = projected_bounds(width, depth)
    town, variant = TOWN_CODES[master_id[0]], int(master_id[1])
    scene_stem = f"as_{town}_{variant}_{width}"
    painting, underlay = ground_underlay(width, depth, master_id[0])
    from arena_surroundings_composition import compose_native_ring
    scenery, composition = compose_native_ring(master_id, width, depth, (full_width, full_height))
    assert scenery.mode == "RGBA" and scenery.size == painting.size
    assert composition["native_prop_scale"] == [1, 1]
    assert all(i["pixel_scale"] == [1, 1] for i in composition["instances"]), "Every original prop/module must retain1:1 pixel scale"
    assert all(i["pixel_scale"] == [1, 1] for i in composition.get("canal_modules", [])), "Every canal module must retain1:1 pixel scale"
    composition["unique_prop_ids"] = sorted({i["id"] for i in composition["instances"] if "id" in i})
    composition["per_side_prop_ids"] = {
        side: sorted({i["id"] for i in composition["instances"] if i.get("side") == side and "id" in i})
        for side in SIDE_NAMES}
    compositor_path = ROOT / "tools/arena_surroundings_composition.py"
    composition["compositor"] = {"path": compositor_path.relative_to(ROOT).as_posix(),
                                 "sha256": sha(compositor_path.read_bytes())}
    layout_path = ROOT / "tools/arena_surroundings_layout.py"
    composition["layout_source"] = {"path": layout_path.relative_to(ROOT).as_posix(),
                                    "sha256": sha(layout_path.read_bytes())}
    painting.alpha_composite(scenery)
    source_alpha = np.asarray(painting.getchannel("A")).copy()
    mask = np.asarray(geometry_mask(width, depth))
    clipped_alpha = np.where(mask, source_alpha, 0).astype(np.uint8)
    painting.putalpha(Image.fromarray(clipped_alpha))
    visible_before_clear = visible_rgba_sha(painting)
    zero_alpha_mask = Image.fromarray(np.where(clipped_alpha == 0, 255, 0).astype(np.uint8))
    painting.paste((0, 0, 0, 0), mask=zero_alpha_mask)
    del zero_alpha_mask
    visible_after_clear = visible_rgba_sha(painting)
    assert visible_before_clear == visible_after_clear, "Transparent pixel clearing altered visible RGBA pixels"
    transparent_clear = {"method": "Set RGBA0 only where the final clipped alpha was0; retain every alpha1..255 pixel",
                         "zero_alpha_pixels_cleared": int(np.count_nonzero(clipped_alpha == 0)),
                         "visible_rgba_sha256_before": visible_before_clear,
                         "visible_rgba_sha256_after": visible_after_clear,
                         "all_visible_rgba_pixels_unchanged": True}
    proof = alpha_proof(clipped_alpha, width, depth, minimum)
    del mask, source_alpha
    records, models, inventory = [], [], []
    expected_files = set()
    for cy in range(0, full_height, PATCH):
        for cx in range(0, full_width, PATCH):
            actual_width, actual_height = min(PATCH, full_width - cx), min(PATCH, full_height - cy)
            if not np.any(clipped_alpha[cy:cy + actual_height, cx:cx + actual_width]):
                continue
            patch_stem = f"{scene_stem}_p{len(models):04d}"
            texture_name, model_name = patch_stem + ".png", patch_stem + ".t"
            texture_path = OVERLAY / "base/setting/arena_surroundings" / texture_name
            model_path = OVERLAY / "base/setting/arena_surroundings" / model_name
            patch = Image.new("RGBA", (PATCH, PATCH), (0, 0, 0, 0))
            patch.paste(painting.crop((cx, cy, cx + actual_width, cy + actual_height)), (0, 0))
            # No trim or per-patch scaling; transparent padding preserves full UV.
            x, y = inside_anchor((cx + PATCH / 2, cy + PATCH / 2), width, depth)
            screen_offset_x = cx - full_width // 2 - 32 * (y - x) + 32
            screen_offset_y = cy - 32 * depth - 16 * (x + y)
            tile = encode_tile(texture_name, PATCH, PATCH, screen_offset_x, screen_offset_y, render_type=1)
            assert tile[68:70] == b"\x01\0" and tile[340:356] == bytes(16)
            assert struct.unpack_from("<HH", tile, 60) == (PATCH, PATCH)
            assert struct.unpack_from("<HH", tile, 334) == (PATCH, PATCH)
            assert tile[64] == 0
            texture_path.parent.mkdir(parents=True, exist_ok=True)
            patch.save(texture_path)
            write(model_path, tile)
            inventory.extend((file_record(texture_path), file_record(model_path)))
            expected_files.update((texture_path, model_path))
            records.append((model_name, x, y))
            sides, art_bounds = classify_patch(np.asarray(patch.getchannel("A")), cx, cy, width, depth)
            models.append({"model_basename": model_name, "texture_basename": texture_name,
                "native_model_sha256": sha(tile), "canvas_origin": [cx, cy],
                "valid_canvas_extent": [actual_width, actual_height], "texture_dimensions": [PATCH, PATCH],
                "world_anchor": [x, y], "side_classification": sides, "art_world_bounds": art_bounds,
                "screen_offset": [screen_offset_x, screen_offset_y],
                "screen_box_before_camera": [cx - full_width // 2, cy - 32 * depth,
                                             cx - full_width // 2 + PATCH, cy - 32 * depth + PATCH],
                "alpha_nonzero_pixels": int(np.count_nonzero(np.asarray(patch.getchannel("A")))),
                "static_flag": 1, "render_as_tile": 0, "interaction_bytes_hex": "00" * 16})
    all_sides = set().union(*(set(m["side_classification"]) for m in models))
    assert all_sides == set(SIDE_NAMES), f"{scene_stem}: native anchors missing sides{set(SIDE_NAMES) - all_sides}"
    anchor_counts = Counter((m["world_anchor"][0], m["world_anchor"][1]) for m in models)
    max_anchor_count = max(anchor_counts.values())
    assert max_anchor_count <= 255, "Native uint8 attachment counter would overflow"
    scene = encode_scene(records)
    assert struct.unpack_from("<3H", scene, 12) == (1, 1, len(records))
    assert scene[32:34] == b"\0\0" and len(scene) == 34 + 72 * len(records)
    scene_path = OVERLAY / "base/maps" / (scene_stem + ".s")
    write(scene_path, scene)
    inventory.append(file_record(scene_path))
    # Roundtrip every serialized scene/TILE/PNG and reconstruct source alpha by
    # decoded native placement, so coordinates and offsets are independently checked.
    reconstructed = np.zeros((full_height, full_width), dtype=np.uint8)
    preview_image = Image.new("RGBA", (full_width, full_height))
    for index in range(len(records)):
        offset = 34 + index * 72
        name_length = scene[offset]
        model_name = scene[offset + 1:offset + 1 + name_length].decode("ascii")
        x, y = struct.unpack_from("<ii", scene, offset + 64)
        tile = (OVERLAY / "base/setting/arena_surroundings" / model_name).read_bytes()
        sx, sy = struct.unpack_from("<hh", tile, 48)
        assert 0 <= x < width and 0 <= y < width and tile[68:70] == b"\x01\0"
        px = 32 * (y - x) + sx - 32 + full_width // 2
        py = 16 * (x + y) + sy + 32 * depth
        assert px % PATCH == 0 and py % PATCH == 0 and 0 <= px < full_width and 0 <= py < full_height
        texture_name = tile[204:204 + tile[203]].decode("ascii")
        with Image.open(OVERLAY / "base/setting/arena_surroundings" / texture_name) as patch:
            assert patch.mode == "RGBA" and patch.size == (PATCH, PATCH)
            alpha = np.asarray(patch.getchannel("A"))
            valid_width, valid_height = min(PATCH, full_width - px), min(PATCH, full_height - py)
            assert not np.any(alpha[valid_height:, :]) and not np.any(alpha[:, valid_width:])
            reconstructed[py:py + valid_height, px:px + valid_width] = alpha[:valid_height, :valid_width]
            preview_image.paste(patch.crop((0, 0, valid_width, valid_height)), (px, py))
    assert np.array_equal(reconstructed, clipped_alpha), f"{scene_stem}: native placement reconstruction differs"
    preview_path = REPORTS / "previews" / (scene_stem + ".png")
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    review_background = Image.new("RGBA", preview_image.size, (32, 29, 21, 255))
    review_background.alpha_composite(preview_image)
    review_background.convert("RGB").resize((1774, 887), Image.Resampling.LANCZOS).save(preview_path)
    viewports = []
    viewport_points = list(zip(SIDE_NAMES, ((0, width / 2), (width / 2, 0), (width, width / 2), (width / 2, width))))
    viewport_points.extend(zip(("corner_origin", "corner_x", "corner_y", "corner_opposite"),
                               ((0, 0), (width, 0), (0, width), (width, width))))
    for side, world_point in viewport_points:
        wx, wy = world_point
        center_x = round(32 * (wy - wx) + full_width / 2)
        center_y = round(16 * (wx + wy) + 32 * depth)
        box = (center_x - 512, center_y - 384, center_x + 512, center_y + 384)
        viewport_path = REPORTS / "viewports" / (scene_stem + "_" + side + ".png")
        viewport_path.parent.mkdir(parents=True, exist_ok=True)
        review_background.crop(box).convert("RGB").save(viewport_path)
        viewports.append({"side": side, "path": viewport_path.relative_to(ROOT).as_posix(),
                          "sha256": sha(viewport_path.read_bytes()), "native_pixel_dimensions": [1024, 768],
                          "canvas_crop": list(box), "rescaling": False,
                          "scope": "Native-size sprite reconstruction crop; no actual game-client screenshot"})
    # Remove obsolete outputs only for this exact generated scene prefix.
    for directory, suffix in ((OVERLAY / "base/setting/arena_surroundings", ".png"),
                              (OVERLAY / "base/setting/arena_surroundings", ".t")):
        for path in directory.glob(scene_stem + "_p*" + suffix):
            if path not in expected_files:
                assert path.resolve().is_relative_to(OVERLAY.resolve())
                path.unlink()
    # Remove only our obsolete prototype PNGs from the superseded directory.
    for path in (OVERLAY / "base/textures").glob(scene_stem + "_p*.png"):
        assert path.resolve().is_relative_to(OVERLAY.resolve())
        path.unlink()
    return {"scene": scene_path.relative_to(OVERLAY).as_posix(), "scene_basename": scene_path.name,
        "scene_sha256": sha(scene), "scene_bytes": len(scene), "master_id": master_id,
        "source": source, "town_code": town, "variant": variant,
        "playable_width": width, "depth": depth, "canvas_dimensions": [full_width, full_height],
        "scene_origin": [0, 0], "cell_footprint": [1, 1], "cell_payload_hex": "0000",
        "world_outer_bounds": [-depth, -depth, width + depth, width + depth],
        "screen_outer_bounds": [-full_width // 2, -32 * depth, full_width // 2, 32 * (width + depth)],
        "canvas_projection": "x=32*(worldY-worldX)+fullWidth/2; y=16*(worldX+worldY)+32*depth",
        "gameplay_hole_screen_vertices": [[0, 0], [-32 * width, 16 * width], [0, 32 * width], [32 * width, 16 * width]],
        "paint_operation": "Original1:1 native city props/canal modules composited over unchanged original ground-brush frames; exact geometric hole/outer clipping; no artwork resize or nonlinear transformation",
        "rendering_pass": "foreground", "no_nonlinear_warp": True,
        "uniform_source_scale": [1, 1], "native_prop_scale": [1, 1], "composition": composition, "ground_underlay": underlay,
        "transparent_rgba_normalization": transparent_clear,
        "anchors_inside_game_grid": True, "max_models_per_anchor": max_anchor_count,
        "native_attachment_limit": 255,
        "native_inner_l1_radius": width / (width + 2 * depth),
        "alpha_proof": proof, "native_anchor_four_sides": sorted(all_sides),
        "native_reconstruction_equals_clipped_master_alpha": True,
        "native_reconstructed_preview": {"path": preview_path.relative_to(ROOT).as_posix(), "sha256": sha(preview_path.read_bytes()), "dimensions": [1774, 887]},
        "native_viewport_previews": viewports,
        "no_interactions": True, "patch_count": len(models), "models": models,
        "files": inventory, "passed": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="+", choices=[f"{town}{n}" for town in TOWN_CODES for n in range(1, 4)],
                        help="Export selected masters only, e.g.--only D1; report marks incomplete full set")
    parser.add_argument("--min-side-coverage", type=float, default=0.95)
    parser.add_argument("--widths", nargs="+", type=int, choices=list(WIDTH_DEPTH), default=list(WIDTH_DEPTH))
    args = parser.parse_args()
    if not 0.95 <= args.min_side_coverage <= 1:
        parser.error("--min-side-coverage must be in[0.95,1]; lowering the required95% coverage is prohibited")
    selected = args.only or [f"{town}{n}" for town in TOWN_CODES for n in range(1, 4)]
    # Validate all requested masters before any filesystem mutation/export.
    sources = {}
    for master_id in selected:
        path = MASTERS / f"{master_id}.png"
        if not path.is_file():
            raise FileNotFoundError(f"Missing master{path}; no export has started")
        sources[master_id] = validate_master(path)
    proof_path = REPORTS / "asset-proof.json"
    previous = json.loads(proof_path.read_text(encoding="utf-8")) if proof_path.exists() else {"scenes": []}
    rebuilding = {(master_id, width) for master_id in selected for width in args.widths}
    compositor_sha = sha((ROOT / "tools/arena_surroundings_composition.py").read_bytes())
    layout_sha = sha((ROOT / "tools/arena_surroundings_layout.py").read_bytes())
    palette_sha = sha((REPORTS / "native-prop-palette/palette.json").read_bytes())
    scenes = [s for s in previous.get("scenes", []) if s.get("no_nonlinear_warp") is True and
              s.get("rendering_pass") == "foreground" and
              s.get("composition", {}).get("compositor", {}).get("sha256") == compositor_sha and
              s.get("composition", {}).get("layout_source", {}).get("sha256") == layout_sha and
              composition_source_current(s, palette_sha) and
              recorded_source_current(s.get("source", {}), "path", "sha256") and
              (s["master_id"], s["playable_width"]) not in rebuilding]
    for master_id in selected:
        for width in args.widths:
            scene = build_scene(master_id, sources[master_id], width, args.min_side_coverage)
            scenes.append(scene)
            print(f"PASS {scene['scene_basename']}: {scene['patch_count']} patches, hole clear, four sides covered")
    scenes.sort(key=lambda s: (s["master_id"], s["playable_width"]))
    # Recheck all recorded files even for a partial build; stale reports fail.
    final_compositor_sha = sha((ROOT / "tools/arena_surroundings_composition.py").read_bytes())
    final_layout_sha = sha((ROOT / "tools/arena_surroundings_layout.py").read_bytes())
    final_palette_sha = sha((REPORTS / "native-prop-palette/palette.json").read_bytes())
    assert all(s["composition"]["compositor"]["sha256"] == final_compositor_sha for s in scenes), "Compositor changed during export; rebuild is required"
    assert all(s["composition"]["layout_source"]["sha256"] == final_layout_sha for s in scenes), "Layout changed during export; rebuild is required"
    assert all(composition_source_current(s, final_palette_sha) for s in scenes), "Palette/canal bank source changed during export; rebuild is required"
    assert all(recorded_source_current(s["source"], "path", "sha256") for s in scenes), "Approved master source changed during export; rebuild is required"
    inventory = {f["path"]: f for s in scenes for f in s["files"]}
    for relative, recorded in inventory.items():
        assert file_record(OVERLAY / relative) == recorded, f"Recorded export changed:{relative}"
    expected = {(f"{town}{n}", width) for town in TOWN_CODES for n in range(1, 4) for width in WIDTH_DEPTH}
    actual = {(s["master_id"], s["playable_width"]) for s in scenes}
    complete = actual == expected
    if not args.only and set(args.widths) == set(WIDTH_DEPTH):
        assert complete and len(scenes) == 24
    native_path = REPORTS / "native.json"
    native = json.loads(native_path.read_text(encoding="utf-8"))
    assert native["status"] == "PASS" and native["schema"] == "arena-surroundings-native/v2-foreground"
    assert native["render_mode"] == "noninteractive_foreground_type1"
    summary = {"passed": True, "full_set_complete": complete, "scene_count": len(scenes),
        "expected_scene_count": 24, "selected_masters": selected, "overlay_root": str(OVERLAY),
        "file_count": len(inventory), "files": sorted(inventory.values(), key=lambda f: f["path"]),
        "source_hashes": {s["master_id"]: s["source"]["sha256"] for s in scenes},
        "all_gameplay_holes_clear": all(s["alpha_proof"]["hole_nonzero_pixels"] == 0 for s in scenes),
        "all_outer_diamonds_clear": all(s["alpha_proof"]["outside_nonzero_pixels"] == 0 for s in scenes),
        "all_four_sides_covered": all(s["alpha_proof"]["passed"] for s in scenes),
        "all_four_corners_covered": all(all(c["opaque_fraction"] >=0.95 for c in s["alpha_proof"]["four_corners"].values()) for s in scenes),
        "all_models_noninteractive": all(s["no_interactions"] for s in scenes),
        "all_scenes_foreground": all(s["rendering_pass"] == "foreground" for s in scenes),
        "all_scenes_no_nonlinear_warp": all(s["no_nonlinear_warp"] for s in scenes),
        "all_visible_pixels_unchanged_by_transparent_clear": all(s["transparent_rgba_normalization"]["all_visible_rgba_pixels_unchanged"] for s in scenes),
        "all_native_anchors_inside_game_grid": all(s["anchors_inside_game_grid"] for s in scenes),
        "maximum_models_per_anchor": max(s["max_models_per_anchor"] for s in scenes),
        "all_scenes_1x1_empty_cells": all(s["cell_footprint"] == [1, 1] and s["cell_payload_hex"] == "0000" for s in scenes),
        "all_patches_1024x1024_full_frame": all(m["texture_dimensions"] == [PATCH, PATCH] for s in scenes for m in s["models"]),
        "native_proof": {"path": native_path.relative_to(ROOT).as_posix(), "sha256": sha(native_path.read_bytes()), "status": native["status"]},
        "scope": "Raster/native-resource export and local automated proofs; no hosted server, GPU or real-client validation"}
    REPORTS.mkdir(parents=True, exist_ok=True)
    proof_path.write_text(json.dumps({"schema": 2, "rendering_pass": "foreground", "no_nonlinear_warp": True, "scenes": scenes}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (REPORTS / "asset-verification.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"PASS {len(scenes)}/24 scenes, {len(inventory)} native files; full_set_complete={complete}")


if __name__ == "__main__":
    main()
