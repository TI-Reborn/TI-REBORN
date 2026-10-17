"""Package original ImageGen PNGs and an authoritative map layout.

The native renderer loads gm-v2-terrain.png and 22 prefixed PNGs separately.
This builder copies bytes, never edits pixels, changes world policies, writes a
database, or installs a client. The output is an isolated candidate directory.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import struct
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets/global-map-v2"
DEFAULT_OUTPUT = ROOT / "reports/global-map-integration-20261010/client/candidate"
DEFAULT_AUTHORITY = ROOT / "reports/global-map-integration-20261010/baseline/runtime/evidence/zones_diagnostic.xml"
RESOURCE_DIR = Path("base/pda/global-map-v2")
RESOURCE_PREFIX = "gm-v2-"
IDS = tuple(range(1, 23))
RUNTIME_IDS = tuple(range(2, 23))
KINDS = {"city", "base", "mine", "prison", "shooting_range", "training_base"}
COLLISION_PAIR = (12, 16)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def png_header(data: bytes) -> dict:
    """Read only the lossless PNG header; no decoder or pixel editing is used."""
    if len(data) < 33 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise ValueError("Expected an original PNG with an IHDR header")
    width, height, depth, color, compression, filtering, interlace = struct.unpack(
        ">IIBBBBB", data[16:29]
    )
    if not (width and height and depth == 8 and color in (2, 6)
            and compression == filtering == 0 and interlace in (0, 1)):
        raise ValueError("Unexpected original PNG dimensions or format")
    return {"pixels": [width, height], "mode": "RGBA" if color == 6 else "RGB"}


def _bounds(values) -> tuple[int, int, int, int]:
    if (not isinstance(values, (list, tuple)) or len(values) != 4
            or any(type(n) is not int or not -512 <= n <= 511 for n in values)
            or values[0] >= values[2] or values[1] >= values[3]):
        raise ValueError("Invalid authoritative world bounds")
    return tuple(values)


def _authority(path: Path | None) -> tuple[dict, dict | None]:
    if path is None:
        return {}, None
    raw = path.read_bytes()
    if b"<!" in raw:
        raise ValueError("Unsupported authority XML declaration")
    root = ET.fromstring(raw)
    if root.tag != "towns" or [int(n.get("id")) for n in root] != list(IDS):
        raise ValueError("Expected the complete ordered 22-location hosted bootstrap")
    records = {}
    for node in root:
        identity = int(node.get("id"))
        values = {n.get("key"): n.get("val") for n in node}
        if values.get("enabled") not in ("0", "1"):
            raise ValueError("Invalid authoritative enabled flag")
        configured = _bounds([int(values[k]) for k in ("x1", "y1", "x2", "y2")])
        size = int(values.get("size", "0"))
        # The verified original 0x9ea894 loader recenters a positive size with
        # round-to-even. NY Base's configured height is 21 rather than 20.
        native = [round((configured[0] + configured[2] + sign * size) / 2)
                  if axis == 0 else round((configured[1] + configured[3] + sign * size) / 2)
                  for sign, axis in ((-1, 0), (-1, 1), (1, 0), (1, 1))] if size > 0 else list(configured)
        records[identity] = {"bounds": configured, "enabled": values["enabled"] == "1",
                             "native_bounds": native, "configured_size": size}
    return records, {"path": str(path.resolve()), "sha256": sha(raw), "location_count": len(records)}


def make_layout(catalog: dict, *, runtime_bounds=None, authority_zones: Path | None = None) -> dict:
    """Keep authoritative hit rectangles and cosmetic draw footprints separate."""
    catalog = deepcopy(catalog)
    rows = catalog.get("locations", [])
    if [r.get("id") for r in rows] != list(IDS):
        raise ValueError("Expected exactly ordered location IDs 1..22")
    if runtime_bounds is None:
        from tio.locations import TOWNS
        runtime_bounds = TOWNS
    runtime_bounds = {i: _bounds(b) for i, b in runtime_bounds.items()}
    if tuple(sorted(runtime_bounds)) != RUNTIME_IDS:
        raise ValueError("Expected exactly authoritative runtime IDs 2..22; Texas is decorative")
    authority, provenance = _authority(authority_zones)
    objects = []
    for row in rows:
        identity = row["id"]
        bounds = _bounds(row["bounds_world"])
        source_filename = row.get("object_asset", "")
        if row.get("kind") not in KINDS or not re.fullmatch(r"[a-z0-9-]+\.png", source_filename):
            raise ValueError("Invalid object kind or safe PNG basename")
        # The original TI texture cache strips both directories and extension.
        # Prefixing prevents aliases with existing assault/denver.tga, etc.
        filename = RESOURCE_PREFIX + source_filename
        if identity != 1 and bounds != runtime_bounds[identity]:
            raise ValueError(f"Catalog location {identity} differs from authoritative runtime bounds")
        if authority and bounds != authority[identity]["bounds"]:
            raise ValueError(f"Catalog location {identity} differs from observed hosted bootstrap")
        center = [(bounds[0] + bounds[2]) // 2, (bounds[1] + bounds[3]) // 2]
        semantic_center = [(bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2]
        diameter = min(bounds[2] - bounds[0], bounds[3] - bounds[1])
        extent = 12.0 if identity in COLLISION_PAIR else round(diameter * 0.8, 6) if row["kind"] == "city" else 16.0
        native_bounds = authority[identity]["native_bounds"] if authority else list(bounds)
        half = extent / 2
        footprint = [center[0] - half, center[1] - half, center[0] + half, center[1] + half]
        for container in (bounds, native_bounds):
            if (footprint[0] < container[0] or footprint[1] < container[1]
                    or footprint[2] > container[2] or footprint[3] > container[3]):
                raise ValueError(f"Draw footprint escapes the location {identity} hit rectangle")
        objects.append({"id": identity, "name": row["name"], "kind": row["kind"],
            "filename": filename, "resource": (RESOURCE_DIR / filename).as_posix(),
            "source_file": "objects/" + source_filename, "source_bounds_world": list(bounds),
            "source_center_world": semantic_center, "draw_center_world": center,
            "native_bounds_world": native_bounds, "world_width": extent, "world_height": extent,
            "draw_bounds_world": footprint, "anchor": [0.5, 0.5],
            "decorative_only": identity == 1, "pickable": identity != 1,
            "authority_enabled": authority[identity]["enabled"] if authority else identity != 1,
            "respect_native_enabled": True})
    filenames = [r["filename"] for r in objects]
    if len(set(filenames)) != len(objects):
        raise ValueError("Object PNG basenames must be unique")
    # Reduced draw quads avoid the inherited MZ Base / Mine 16-20 overlap.
    by_id = {r["id"]: r for r in objects}
    if intersect(by_id[12]["draw_bounds_world"], by_id[16]["draw_bounds_world"]):
        raise ValueError("The MZ Base and Mine 16-20 visual footprints collide")
    return {"schema": 1, "coordinate_system": "X right, Y down; original world units",
        "world_quad_bounds": [-512, -512, 512, 512], "accepted_travel_bounds": [-512, -512, 511, 511],
        "terrain": {"filename": RESOURCE_PREFIX + "terrain.png", "resource": (RESOURCE_DIR / (RESOURCE_PREFIX + "terrain.png")).as_posix(),
                    "source_file": "global-map-terrain.png", "world_bounds": [-512, -512, 512, 512]},
        "drawing": {"layers": ["terrain", "objects", "native_markers_and_tooltips"],
                    "independent_original_pngs": True, "baked_objects": False,
                    "viewport_mapping": "Use the same affine viewport transform for terrain, sprites, native labels, actors and inverse map input",
                    "source_pixel_edits": False},
        "authority": provenance, "object_count": len(objects), "objects": objects,
        "known_inherited_hit_overlap": {"ids": [12, 16], "intersection_world": [255, -170, 261, -155],
            "server_overlap_choice": 16, "world_policies_changed": False,
            "cosmetic_solution": "Two 12-unit sprite quads with a 2-unit horizontal gap"}}


def intersect(a, b) -> bool:
    return max(a[0], b[0]) < min(a[2], b[2]) and max(a[1], b[1]) < min(a[3], b[3])


def project(point, viewport):
    left, top, width, height = viewport
    if width <= 0 or height <= 0:
        raise ValueError("Viewport must have positive dimensions")
    return left + (point[0] + 512) * width / 1024, top + (point[1] + 512) * height / 1024


def unproject(point, viewport):
    left, top, width, height = viewport
    if width <= 0 or height <= 0:
        raise ValueError("Viewport must have positive dimensions")
    return (point[0] - left) * 1024 / width - 512, (point[1] - top) * 1024 / height - 512


def build(output: Path = DEFAULT_OUTPUT, *, source: Path = SOURCE, runtime_bounds=None,
          authority_zones: Path | None = None) -> dict:
    source, output = source.resolve(), output.resolve()
    if output == source or source in output.parents or output in source.parents:
        raise ValueError("Output must be isolated from the original asset directory")
    catalog_bytes = (source / "catalog.json").read_bytes()
    manifest_bytes = (source / "asset-manifest.json").read_bytes()
    originals = {r["file"]: r for r in json.loads(manifest_bytes)["images"]}
    layout = make_layout(json.loads(catalog_bytes), runtime_bounds=runtime_bounds, authority_zones=authority_zones)
    destination = output / RESOURCE_DIR
    files = []
    # Validate every source before writing any candidate files.
    staged = []
    for record in (layout["terrain"], *layout["objects"]):
        name = record["source_file"]
        raw = (source / name).read_bytes()
        meta = png_header(raw)
        pinned = originals.get(name)
        if (pinned is None or sha(raw) != pinned["sha256"]
                or meta["pixels"] != pinned["pixels"] or meta["mode"] != pinned["mode"]):
            raise ValueError(f"Original image changed or is invalid: {name}")
        if name.startswith("objects/") and meta["mode"] != "RGBA":
            raise ValueError("Object textures must preserve their original alpha channel")
        staged.append((record, raw))
        files.append({"source": name, "path": record["resource"], "size": len(raw),
                      "sha256": sha(raw), **meta, "copy_byte_for_byte": True})
    if len(files) != 23 or len({r["path"] for r in files}) != 23:
        raise ValueError("Expected exactly 23 original PNG resources")
    destination.mkdir(parents=True, exist_ok=True)
    # Remove only earlier copies of these same original images. This migration
    # never removes a different file, and prevents a stale unprefixed package.
    for record, raw in staged:
        old_target = destination / record["filename"].removeprefix(RESOURCE_PREFIX)
        if old_target.exists():
            if old_target.is_symlink() or old_target.read_bytes() != raw:
                raise ValueError("Unprefixed candidate differs from the original PNG")
            old_target.unlink()
    for record, raw in staged:
        target = destination / record["filename"]
        target.write_bytes(raw)
        if sha(target.read_bytes()) != sha(raw):
            raise ValueError("Candidate copy verification failed")
    layout_bytes = (json.dumps(layout, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    (destination / "layout.json").write_bytes(layout_bytes)
    result = {"schema": 1, "source_catalog_sha256": sha(catalog_bytes),
        "source_manifest_sha256": sha(manifest_bytes), "layout_sha256": sha(layout_bytes),
        "png_count": len(files), "object_count": 22, "files": files,
        "software_pixel_edits": False, "originals_preserved": True,
        "runtime_world_policies_changed": False, "database_opened": False,
        "installed_client_changed": False, "published": False,
        "native_rendering_verified": False, "real_client_validation": False}
    (destination / "manifest.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--authority-zones", type=Path,
                        default=DEFAULT_AUTHORITY if DEFAULT_AUTHORITY.exists() else None)
    args = parser.parse_args()
    report = build(args.output, source=args.source, authority_zones=args.authority_zones)
    print(json.dumps({"passed": True, "png_count": report["png_count"],
                      "object_count": report["object_count"], "output": str(args.output.resolve()),
                      "originals_preserved": True, "software_pixel_edits": False}, indent=2))
