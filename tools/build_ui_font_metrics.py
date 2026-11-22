"""Rasterize the UI faces with their own metrics for the native font adapter.

Unlike tools/build_native_ui_fonts.py (Roboto ink centred in the original pixel-font
cells), every glyph here carries the face's own whole-pixel advance, its ink offset
from the pen and GPOS pair kerning, so the native measure and draw loops (TI6fdcb4,
TI6fcd84) space letters the way the face was designed. Line height and the glyph
'top' stay native: window layouts are built on them.

Text roles use IBM Plex Sans Condensed; the extra "title" role (a separate TI font
object loaded from pixel.xml, used only for window captions) uses Tektur. Every
glyph carries a baked 1 px dark shadow: the adapter tints glyphs by multiplying
the colour, so black shadow pixels stay black under any text colour.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
import statistics
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.export_native_font_atlas import pack  # noqa: E402
from tools.font_kerning import Kerning  # noqa: E402

FONTS_DIR = ROOT / "reports/ui-hd-assets/fonts"
BASELINE = ROOT / "reports/ui-hd-assets/font-atlases/baseline-original"
OUTPUT = ROOT / "reports/ui-fonts-titles-20261120"
SCALES = (100, 125, 150, 200)
# Typographic marks the original atlases lack; each role gets the ones it does not have.
EXTRA = "–—«»„“”…№×"
GLYPH_LIMIT = 0x100  # the draw adapter rejects larger per-font tables
KERN_RANGE = (-128, 127)  # TFontLetterGroups.Spec clamps the shift to a ShortInt
# Native loops keep the previous kerning glyph across a record-less space, so "Т о" would kern
# T-o through the gap. A real (transparent) space record resets it; no pair involves the space.
SPACE = " "
SHADOW_ALPHA = 0.75  # of the ink's own alpha, offset one logical pixel right and down


@dataclass(frozen=True)
class Face:
    family: str
    folder: str
    sha256: str
    licence: str
    width: int

    @property
    def path(self) -> Path:
        return FONTS_DIR / self.folder / "variable.ttf"

    def font(self, size: int, weight: int) -> ImageFont.FreeTypeFont:
        font = ImageFont.truetype(str(self.path), size)
        wanted = {b"Weight": weight, b"Width": self.width}
        font.set_variation_by_axes([wanted[axis["name"]] for axis in font.get_variation_axes()])
        return font


@dataclass(frozen=True)
class Role:
    name: str     # adapter role; also the atlas name
    native: str   # original font XML that defines cap height, baseline, line height and tops
    face: Face
    weight: int
    prefix: str


PLEX = Face("IBM Plex Sans Condensed", "ibm-plex-sans",
            "3b031aa4216174205bd8471f88a49b91f093169e9e87bd5262242bc5967fe2e3", "IBMPlexSans-OFL.txt", 85)
TEKTUR = Face("Tektur", "tektur",
              "a4c451e5336874811267c2a514efa09bca7bc8cabf32a310f0b44e111eacb933", "Tektur-OFL.txt", 100)
WEIGHTS = {"pixelb": 600, "big": 600, "pixel14": 600, "nice": 500, "menu": 500}
ROLES = tuple(Role(stem, stem, PLEX, WEIGHTS.get(stem, 400), "plexc")
              for stem in ("font1", "pixel", "pixelb", "nice", "mini", "big", "pixel13", "pixel14", "menu")) + (
    Role("title", "pixel", TEKTUR, 600, "tektur"),)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ink(font: ImageFont.FreeTypeFont, character: str) -> tuple[Image.Image, tuple[int, int]]:
    """Ink-cropped glyph (alpha) and its offset from the pen origin on the baseline."""
    if character == SPACE:
        return Image.new("L", (1, 1), 0), (0, 0)
    left, top, right, bottom = font.getbbox(character, anchor="ls")
    mask = Image.new("L", (max(1, right - left), max(1, bottom - top)), 0)
    ImageDraw.Draw(mask).text((-left, -top), character, font=font, fill=255, anchor="ls")
    bounds = mask.getbbox()
    if bounds is None:
        raise ValueError(f"Empty source glyph U+{ord(character):04X}")
    return mask.crop(bounds), (left + bounds[0], top + bounds[1])


def shadowed(alpha: Image.Image, offset: int) -> Image.Image:
    """White ink over a black copy shifted by offset pixels; a 1x1 empty cell stays empty."""
    if alpha.getbbox() is None:
        return Image.new("RGBA", alpha.size, (255, 255, 255, 0))
    cell = Image.new("RGBA", (alpha.width + offset, alpha.height + offset), (0, 0, 0, 0))
    shadow = Image.new("RGBA", alpha.size, (0, 0, 0, 255))
    shadow.putalpha(alpha.point(lambda v: round(v * SHADOW_ALPHA)))
    cell.alpha_composite(shadow, (offset, offset))
    text = Image.new("RGBA", alpha.size, (255, 255, 255, 255))
    text.putalpha(alpha)
    cell.alpha_composite(text, (0, 0))
    return cell


def glyph_box(character: str, denses: dict[int, ImageFont.FreeTypeFont],
              baseline: int) -> tuple[list[int], dict[int, Image.Image]]:
    """Logical box (pen-relative x, line-relative y, w, h) covering the glyph at every density,
    and one cell per density exactly box*scale in size with the ink at its own position.

    The adapter places a glyph at logical (pen + dx, line + dy) and stretches the cell over
    box*scale. Rounding the ink offset to a logical pixel at 100 % and scaling it would misplace
    ink by up to a scaled pixel per letter (visible as uneven gaps at 150 %), so each density
    positions its own raster inside the shared logical box instead.
    """
    rasters, extents = {}, []
    for scale, dense in denses.items():
        s = scale / 100
        alpha, (dx, dy) = ink(dense, character)
        shadow = 0 if alpha.getbbox() is None else max(1, (scale + 50) // 100)
        rasters[scale] = (alpha, dx, dy, shadow)
        extents.append((dx / s, baseline + dy / s, (dx + alpha.width + shadow) / s,
                        baseline + (dy + alpha.height + shadow) / s))
    left = math.floor(min(e[0] for e in extents))
    top = math.floor(min(e[1] for e in extents))
    right = math.ceil(max(e[2] for e in extents) - 1e-9)
    bottom = math.ceil(max(e[3] for e in extents) - 1e-9)
    cells = {}
    for scale, (alpha, dx, dy, shadow) in rasters.items():
        s = scale / 100
        cell = Image.new("RGBA", (max(1, round((right - left) * s)), max(1, round((bottom - top) * s))),
                         (255, 255, 255, 0))
        # Clipping at the far edge loses at most the last shadow column to rounding.
        cell.alpha_composite(shadowed(alpha, max(1, shadow)),
                             (round(dx - left * s), round(baseline * s + dy - top * s)))
        cells[scale] = cell
    return [left, top, right - left, bottom - top], cells


def native_role(stem: str) -> tuple[ET.Element, list[dict]]:
    root = ET.parse(BASELINE / f"{stem}.xml").getroot()
    glyphs = [{"codepoint": int(item.attrib.get("ascii", item.attrib.get("ucode", "-1"))),
               "top": int(item.attrib["top"]), "height": int(item.attrib["height"])} for item in root]
    return root, sorted(glyphs, key=lambda g: g["codepoint"])


def fitted_size(role: Role, cap_height: int, line_height: int) -> int:
    """Same rule as the Roboto builder: the size whose 'H' ink matches the native cap height."""
    return min(range(5, 65), key=lambda s: (abs(ink(role.face.font(s, role.weight), "H")[0].height - cap_height),
                                            abs(s - line_height)))


def kerning_pairs(kern: Kerning, codepoints: list[int], size: int) -> list[list[int]]:
    pairs = []
    letters = [c for c in codepoints if c != ord(SPACE)]
    for first in letters:
        for second in letters:
            shift = kern.pixels(first, second, size)
            if shift:
                pairs.append([first, second, max(KERN_RANGE[0], min(KERN_RANGE[1], shift))])
    return pairs


def build_role(role: Role, kern: Kerning, output: Path) -> tuple[dict, list[dict]]:
    root, native = native_role(role.native)
    caps = [g for g in native if 65 <= g["codepoint"] <= 90]
    cap_height = int(statistics.median(g["height"] for g in caps))
    baseline = int(statistics.median(g["top"] + g["height"] for g in caps))
    line_height = int(root.attrib["height"])
    size = fitted_size(role, cap_height, line_height)
    base = role.face.font(size, role.weight)
    known = {g["codepoint"] for g in native}
    tops = {g["codepoint"]: g["top"] for g in native}
    heights = {g["codepoint"]: g["height"] for g in native}
    codepoints = sorted(known | {ord(c) for c in EXTRA + SPACE if ord(c) in kern.cmap})
    if len(codepoints) > GLYPH_LIMIT:
        raise ValueError(f"{role.name}: {len(codepoints)} glyphs exceed the adapter table")
    denses = {scale: role.face.font(max(1, (size * scale + 50) // 100), role.weight) for scale in SCALES}
    glyphs, cells = [], {scale: [] for scale in SCALES}
    for codepoint in codepoints:
        top = tops.get(codepoint, 0)  # added glyphs get a zero native top
        advance = round(base.getlength(chr(codepoint)))
        if advance < 1:
            raise ValueError(f"{role.name}: U+{codepoint:04X} has no advance")
        box, density_cells = glyph_box(chr(codepoint), denses, baseline)
        # The native loops skip records whose height is below 1; added glyphs need one.
        glyphs.append({"codepoint": codepoint, "advance": advance, "top": top,
                       "height": heights.get(codepoint, max(1, box[3])),
                       "visual_logical_box": [box[0], box[1] - top, box[2], box[3]],
                       "added": codepoint not in known, "source_rects": []})
        for scale in SCALES:
            cells[scale].append(density_cells[scale])
    assets, density_sets = [], []
    for scale in SCALES:
        atlas, rects = pack(cells[scale])
        relative = f"base/ui-hd/fonts/{role.prefix}-{role.name}-{scale}.png"
        path = output / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        atlas.save(path, optimize=False, compress_level=9)
        for glyph, rect in zip(glyphs, rects):
            glyph["source_rects"].append(list(rect))
        asset = {"path": relative, "sha256": sha(path), "bytes": path.stat().st_size,
                 "width": atlas.width, "height": atlas.height, "scale": scale, "font": role.name}
        assets.append(asset)
        density_sets.append(asset)
    manifest_role = {"font": role.name, "family": role.face.family, "native_xml": role.native,
                     "original_xml_sha256": sha(BASELINE / f"{role.native}.xml"),
                     "logical_line_metrics": {"width": int(root.attrib["width"]), "height": line_height},
                     "native_cap_height": cap_height, "native_baseline": baseline,
                     "uniform_font_pixel_size_100": size, "weight": role.weight, "width_axis": role.face.width,
                     "extra_spacing": 0, "space_advance": round(base.getlength(SPACE)),
                     "kerning": kerning_pairs(kern, codepoints, size),
                     "glyphs": glyphs, "density_sets": density_sets}
    return manifest_role, assets


def build(output: Path = OUTPUT) -> dict:
    output = output.absolute()
    faces = {role.face for role in ROLES}
    for face in faces:
        if sha(face.path) != face.sha256:
            raise ValueError(f"{face.family} source differs")
    kerning = {face: Kerning(face.path) for face in faces}
    roles, assets = [], []
    for role in ROLES:
        manifest_role, role_assets = build_role(role, kerning[role.face], output)
        roles.append(manifest_role)
        assets += role_assets
    for face in sorted(faces, key=lambda f: f.family):
        target = output / "base/ui-hd/licenses" / face.licence
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((face.path.parent / "OFL.txt").read_bytes())
        assets.append({"path": f"base/ui-hd/licenses/{face.licence}", "sha256": sha(target),
                       "bytes": target.stat().st_size})
    manifest = {"schema": 2, "result": "PASS", "family": "IBM Plex Sans Condensed + Tektur titles",
                "sources": {face.family: face.sha256 for face in faces}, "scales": list(SCALES),
                "shadow": {"offset_logical_px": 1, "alpha": SHADOW_ALPHA},
                "assets": assets, "fonts": roles,
                "native_metrics_replaced": ["advance", "extra_spacing", "space_advance", "kerning"],
                "native_metrics_kept": ["line_height", "glyph_top"]}
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    manifest = build(args.output)
    print(json.dumps({"roles": len(manifest["fonts"]), "assets": len(manifest["assets"]),
                      "glyphs": {f["font"]: len(f["glyphs"]) for f in manifest["fonts"]},
                      "kerning_pairs": {f["font"]: len(f["kerning"]) for f in manifest["fonts"]},
                      "manifest_sha256": sha(args.output / "manifest.json")}))


if __name__ == "__main__":
    main()
