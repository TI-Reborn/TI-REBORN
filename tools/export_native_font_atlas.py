"""Offline native TI bitmap-font prototypes, with unchanged logical metrics.

This creates review assets only.  The density PNGs are NOT drop-in replacements:
TI uses one XML rectangle for both texture coordinates and destination geometry.
An eventual font-only adapter must select the new source rectangle independently.
No client process, installed asset, binary or hosted service is changed here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SCALES = (100, 125, 150, 200)
FONT_ORDER = ("font1", "pixel", "pixelb", "nice", "mini", "big", "pixel13", "pixel14")
EXTRA_FONTS = ("pixelu", "menu")
# 'menu' is loaded later by the published scoped menu presentation patch.
SELECTOR = {"font1": 0, "pixel": 1, "pixelb": 2, "nice": 3, "mini": 4,
            "big": 6, "pixel13": 7, "pixel14": 8, "menu": 3}
SPACING = {"pixel": 0, "pixelb": 0, "big": 2}
WEIGHTS = {"pixelb": 600, "big": 600, "pixel14": 600, "nice": 500, "menu": 500}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def physical(value: int, percent: int) -> int:
    return max(1, (value * percent + 50) // 100)


def load_logical(path: Path) -> tuple[dict, list[dict]]:
    root = ET.parse(path).getroot()
    if root.tag != "font":
        raise ValueError(f"Not a native font XML: {path}")
    rows = []
    seen = set()
    for item in root:
        if item.tag != "item":
            raise ValueError(f"Unexpected native font tag: {item.tag}")
        code = int(item.attrib.get("ascii", item.attrib.get("ucode", "-1")))
        if not 0 <= code <= 0xFFFF or code in seen:
            raise ValueError(f"Invalid/duplicate code point: {code}")
        seen.add(code)
        metrics = {name: int(item.attrib.get(name, "0")) for name in
                   ("top", "x", "y", "width", "height", "leading", "trailing")}
        if metrics["width"] <= 0 or metrics["height"] <= 0:
            raise ValueError(f"Empty native glyph: {code}")
        rows.append({"codepoint": code, "character": chr(code), "logical": metrics})
    return {"width": int(root.attrib["width"]), "height": int(root.attrib["height"])}, rows


def font_at(path: Path, size: int, axes: list[dict], weight: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(path), size)
    if axes:
        values = [float(weight) if a["tag"] == "wght" else float(a["default"]) for a in axes]
        for value, axis in zip(values, axes):
            if not float(axis["min"]) <= value <= float(axis["max"]):
                raise ValueError(f"Requested font axis exceeds source range: {axis['tag']}")
        font.set_variation_by_axes(values)
    return font


def raster_cell(font: ImageFont.FreeTypeFont, character: str, width: int, height: int) -> tuple[Image.Image, dict]:
    left, top, right, bottom = font.getbbox(character, anchor="ls")
    natural_w, natural_h = right - left, bottom - top
    if natural_w <= 0 or natural_h <= 0:
        raise ValueError(f"Source has no visible raster for U+{ord(character):04X}")
    mask = Image.new("L", (natural_w, natural_h), 0)
    ImageDraw.Draw(mask).text((-left, -top), character, font=font, fill=255, anchor="ls", stroke_width=0)
    if mask.getbbox() is None:
        raise ValueError(f"Source raster is empty for U+{ord(character):04X}")
    # Keep all old advances, bearings, destinations and line heights. New shapes
    # fit their existing visual cells without aspect distortion or raster upscale.
    fit = min(1.0, width / natural_w, height / natural_h)
    fitted_w = max(1, min(width, int(math.floor(natural_w * fit + 0.5))))
    fitted_h = max(1, min(height, int(math.floor(natural_h * fit + 0.5))))
    if (fitted_w, fitted_h) != mask.size:
        mask = mask.resize((fitted_w, fitted_h), Image.Resampling.LANCZOS)
    cell = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    alpha = Image.new("L", (width, height), 0)
    # Native 'top' already places this cell; bottom alignment retains descender
    # cells. This compatibility prototype does not claim original TTF bearings.
    offset = ((width - fitted_w) // 2, height - fitted_h)
    alpha.paste(mask, offset)
    cell.putalpha(alpha)
    return cell, {"natural_raster_size": [natural_w, natural_h],
                  "source_bearing_at_density": [left, top], "fit_ratio": fit,
                  "fitted_raster_size": [fitted_w, fitted_h], "cell_offset": list(offset),
                  "raster_upscaled": False}


def pack(cells: list[Image.Image]) -> tuple[Image.Image, list[list[int]]]:
    gutter = 2
    area = sum((c.width + 2 * gutter) * (c.height + 2 * gutter) for c in cells)
    width = 128
    while width < math.sqrt(area) or width < max(c.width + 2 * gutter for c in cells):
        width *= 2
    x = y = row_h = gutter
    rectangles = []
    for cell in cells:
        if x + cell.width + gutter > width:
            x, y, row_h = gutter, y + row_h + gutter, 0
        rectangles.append([x, y, cell.width, cell.height])
        x += cell.width + 2 * gutter
        row_h = max(row_h, cell.height + gutter)
    required_h = y + row_h + gutter
    height = 128
    while height < required_h:
        height *= 2
    atlas = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    for cell, (x, y, _, _) in zip(cells, rectangles):
        atlas.paste(cell, (x, y))
    return atlas, rectangles


def check_atlas(path: Path, rows: list[dict], original: list[dict], line_metrics: dict,
                original_line_metrics: dict) -> dict:
    """Asset contract validation; no emulated cache, renderer or font API."""
    atlas = Image.open(path)
    if atlas.mode != "RGBA" or line_metrics != original_line_metrics:
        raise ValueError("Unexpected atlas format or modified line metrics")
    expected = {r["codepoint"]: r["logical"] for r in original}
    actual = {r["codepoint"]: r["logical"] for r in rows}
    if len(actual) != len(rows) or actual != expected:
        raise ValueError("Coverage/uniqueness/logical metrics changed")
    rectangles = []
    for row in rows:
        x, y, w, h = row["source_rect"]
        if min(x, y) < 2 or min(w, h) <= 0 or x + w + 2 > atlas.width or y + h + 2 > atlas.height:
            raise ValueError("Source rectangle outside atlas/gutter")
        if atlas.crop((x, y, x + w, y + h)).getchannel("A").getbbox() is None:
            raise ValueError("Empty glyph source rectangle")
        for ox, oy, ow, oh in rectangles:
            if x < ox + ow and ox < x + w and y < oy + oh and oy < y + h:
                raise ValueError("Overlapping source rectangles")
        rectangles.append([x, y, w, h])
        if row["raster_upscaled"]:
            raise ValueError("Raster enlargement is forbidden")
    return {"result": "PASS", "glyphs": len(rows), "coverage_exact": True,
            "metrics_exact": True, "line_metrics_exact": True, "source_bounds_valid": True,
            "source_rectangles_unique_and_disjoint": True, "glyphs_nonempty": True,
            "raster_upscaled": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fonts", type=Path, default=ROOT / "reports/ui-hd-assets/fonts")
    parser.add_argument("--baseline", type=Path,
                        default=Path(r"C:\Users\jundu\AppData\Local\TIO-Online\base\fonts"))
    parser.add_argument("--output", type=Path, default=ROOT / "reports/ui-hd-assets/font-atlases")
    args = parser.parse_args()
    candidates = json.loads((args.fonts / "candidates.json").read_text(encoding="utf-8"))
    if candidates.get("result") != "PASS":
        raise ValueError("Source candidate validation is not PASS")
    deps = args.fonts / "_validation-deps"
    if deps.exists():
        sys.path.insert(0, str(deps))
    from fontTools.ttLib import TTFont

    baseline_dir = args.output / "baseline-original"
    baseline_dir.mkdir(parents=True, exist_ok=True)
    baseline_fonts = []
    for stem in (*FONT_ORDER, *EXTRA_FONTS):
        source_xml = args.baseline / f"{stem}.xml"
        source_png = args.baseline / f"{stem}.png"
        logical, glyphs = load_logical(source_xml)
        for source in (source_xml, source_png):
            target = baseline_dir / source.name
            if target.exists() and target.read_bytes() != source.read_bytes():
                raise ValueError(f"Refusing to replace differing original baseline: {target}")
            shutil.copyfile(source, target)
        baseline_fonts.append({"stem": stem, "native_selector": SELECTOR.get(stem),
                               "native_manager_registration_ordinal": FONT_ORDER.index(stem) if stem in FONT_ORDER else None,
                               "logical_line_metrics": logical, "glyphs": glyphs,
                               "xml_sha256": sha(source_xml), "png_sha256": sha(source_png),
                               "native_extra_spacing": SPACING.get(stem, 1), "native_space_advance": 5,
                               "native_extra_line_spacing": 2})

    sets = []
    for candidate in candidates["candidates"]:
        source = args.fonts / candidate["id"] / "variable.ttf"
        if sha(source) != candidate["ttf"]["sha256"]:
            raise ValueError("Candidate TTF differs from pinned manifest")
        with TTFont(source) as tt:
            coverage = set(tt.getBestCmap())
        for percent in SCALES:
            folder = args.output / candidate["id"] / str(percent)
            folder.mkdir(parents=True, exist_ok=True)
            for baseline in baseline_fonts:
                missing = sorted({r["codepoint"] for r in baseline["glyphs"]} - coverage)
                if missing:
                    raise ValueError(f"Original character coverage missing: {missing}")
                stem = baseline["stem"]
                size = physical(baseline["logical_line_metrics"]["height"], percent)
                weight = WEIGHTS.get(stem, 400)
                font = font_at(source, size, candidate["font_metadata"]["axes"], weight)
                cells, rasters = [], []
                for glyph in baseline["glyphs"]:
                    logical = glyph["logical"]
                    cell, raster = raster_cell(font, glyph["character"],
                                               physical(logical["width"], percent),
                                               physical(logical["height"], percent))
                    cells.append(cell)
                    rasters.append(raster)
                atlas, rects = pack(cells)
                atlas_path = folder / f"{stem}.png"
                atlas.save(atlas_path, optimize=False, compress_level=9)
                # Exact byte copy documents the logical contract; it is not a
                # native XML for this repacked PNG and must not be deployed alone.
                xml_path = folder / f"{stem}.logical.xml"
                shutil.copyfile(baseline_dir / f"{stem}.xml", xml_path)
                rows = []
                for glyph, rect, raster in zip(baseline["glyphs"], rects, rasters):
                    rows.append({**glyph, "source_rect": rect, **raster,
                                 "native_pen_advance_without_pair_kerning":
                                 glyph["logical"]["leading"] + glyph["logical"]["width"] +
                                 glyph["logical"]["trailing"] + baseline["native_extra_spacing"]})
                validation = check_atlas(atlas_path, rows, baseline["glyphs"],
                                         baseline["logical_line_metrics"], baseline["logical_line_metrics"])
                if sha(xml_path) != baseline["xml_sha256"]:
                    raise ValueError("Logical XML changed")
                contract = {"schema": 1, "scope": "offline compatibility prototype; native adapter required",
                            "candidate": candidate["id"], "family": candidate["family"],
                            "font_stem": stem, "native_selector": baseline["native_selector"],
                            "native_manager_registration_ordinal": baseline["native_manager_registration_ordinal"],
                            "selector_limit": "Identify actual object/texture; menu temporarily shares selector3 with nice.",
                            "percent": percent,
                            "font_source_sha256": sha(source), "raster_font_pixel_size": size,
                            "raster_weight": weight, "atlas_size": list(atlas.size), "atlas_sha256": sha(atlas_path),
                            "logical_xml_sha256": sha(xml_path),
                            "logical_line_metrics": baseline["logical_line_metrics"],
                            "native_extra_spacing": baseline["native_extra_spacing"],
                            "native_space_advance": baseline["native_space_advance"],
                            "native_extra_line_spacing": baseline["native_extra_line_spacing"],
                            "unknown_unicode_behavior": "forward unchanged to original native font",
                            "glyphs_fitted_below_natural_raster": sum(r["fit_ratio"] < 1 for r in rows),
                            "fit_limit": "Compatibility cells preserve old metrics; visual bearings differ from unrestricted TTF.",
                            "glyphs": rows, "validation": validation}
                contract_path = folder / f"{stem}.atlas.json"
                write_json(contract_path, contract)
                sets.append({"candidate": candidate["id"], "percent": percent, "font_stem": stem,
                             "atlas": str(atlas_path.resolve()), "contract": str(contract_path.resolve()),
                             "atlas_sha256": sha(atlas_path), "contract_sha256": sha(contract_path),
                             "glyphs": len(rows), "fitted_glyphs": contract["glyphs_fitted_below_natural_raster"],
                             "validation": validation})
    manifest = {"schema": 1, "result": "PASS", "scope": "offline assets only; no integration or client test",
                "scales": list(SCALES), "candidate_manifest_sha256": sha(args.fonts / "candidates.json"),
                "exporter_sha256": sha(Path(__file__)), "atlas_sets": len(sets),
                "original_loaded_fonts": list(FONT_ORDER), "additional_disk_fonts": list(EXTRA_FONTS),
                "logical_xml_preserved_byte_exact": True, "glyphs_rasterized_from_ttf_at_each_density": True,
                "unknown_unicode_fallback": "original native font unchanged",
                "native_drop_in_compatible": False, "native_adapter_implemented": False,
                "limitations": ["Old logical glyph boxes can constrain new face bearings and proportions.",
                                "Preview assets do not prove native sampling, reset lifecycle or actual game appearance.",
                                "Native adapter must select source rectangles separately from destination metrics."],
                "sets": sets}
    write_json(args.output / "manifest.json", manifest)
    print(json.dumps({"result": "PASS", "atlas_sets": len(sets),
                      "manifest": str((args.output / "manifest.json").resolve())}))


if __name__ == "__main__":
    main()
