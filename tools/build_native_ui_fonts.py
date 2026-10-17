"""Rasterize the selected Roboto Condensed face for the native font adapter.

Each role uses one uniform point size; glyphs are never squeezed into old cells.
Native advances/line metrics remain unchanged. Adapter-only ink bounds permit
small optical overhangs, and density PNGs are rasterized separately from TTF.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import statistics
import sys
from pathlib import Path
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.export_native_font_atlas import pack

SCALES = (100, 125, 150, 200)
FONTS = ("font1", "pixel", "pixelb", "nice", "mini", "big", "pixel13", "pixel14", "menu")
WEIGHTS = {"pixelb": 600, "big": 600, "pixel14": 600, "nice": 500, "menu": 500}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def face(path, size, weight, axes):
    font = ImageFont.truetype(str(path), size)
    if axes:
        font.set_variation_by_axes([weight if a["tag"] == "wght" else a["default"] for a in axes])
    return font


def ink(font, character):
    left, top, right, bottom = font.getbbox(character, anchor="ls")
    mask = Image.new("L", (right-left, bottom-top), 0)
    ImageDraw.Draw(mask).text((-left, -top), character, font=font, fill=255, anchor="ls")
    bounds = mask.getbbox()
    if bounds is None:
        raise ValueError(f"Empty source glyph U+{ord(character):04X}")
    cropped = mask.crop(bounds)
    result = Image.new("RGBA", cropped.size, (255, 255, 255, 0))
    result.putalpha(cropped)
    return result, (left+bounds[0], top+bounds[1])


def build(output):
    output = Path(output).absolute()
    output.mkdir(parents=True, exist_ok=True)
    sources = ROOT / "reports/ui-hd-assets/fonts"
    source_manifest = json.loads((sources / "candidates.json").read_text(encoding="utf-8"))
    candidate = next(c for c in source_manifest["candidates"] if c["id"] == "technical-roboto-condensed")
    ttf = sources / candidate["id"] / "variable.ttf"
    if sha(ttf) != candidate["ttf"]["sha256"]:
        raise ValueError("Selected font source differs")
    baseline = ROOT / "reports/ui-hd-assets/font-atlases/baseline-original"
    compatibility = json.loads((baseline.parent / "manifest.json").read_text(encoding="utf-8"))
    deps = sources / "_validation-deps"
    if deps.exists():
        sys.path.insert(0, str(deps))
    from fontTools.ttLib import TTFont
    with TTFont(ttf) as ft:
        coverage = set(ft.getBestCmap())
    fonts, assets = [], []
    for stem in FONTS:
        original_path = baseline / (stem+".xml")
        prior = next(s for s in compatibility["sets"] if s["candidate"] == candidate["id"]
                     and s["percent"] == 100 and s["font_stem"] == stem)
        prior_contract = json.loads(Path(prior["contract"]).read_text(encoding="utf-8"))
        if sha(original_path) != prior_contract["logical_xml_sha256"]:
            raise ValueError("Original logical font changed")
        tree = ET.parse(original_path).getroot()
        logical = []
        for item in tree:
            code = int(item.attrib.get("ascii", item.attrib.get("ucode", "-1")))
            if code not in coverage:
                raise ValueError("Original glyph missing from selected face")
            logical.append({"codepoint": code, **{n:int(item.attrib.get(n,"0")) for n in
                            ("top", "x", "y", "width", "height", "leading", "trailing")}})
        logical.sort(key=lambda r:r["codepoint"])
        if len({g["codepoint"] for g in logical}) != len(logical):
            raise ValueError("Duplicate original glyph")
        cap = [g for g in logical if 65 <= g["codepoint"] <= 90]
        cap_height = int(statistics.median(g["height"] for g in cap))
        native_baseline = int(statistics.median(g["top"]+g["height"] for g in cap))
        weight = WEIGHTS.get(stem, 400)
        axes = candidate["font_metadata"]["axes"]
        sizes = []
        for size in range(5, 65):
            raster, _ = ink(face(ttf,size,weight,axes), "H")
            sizes.append((abs(raster.height-cap_height), abs(size-int(tree.attrib["height"])), size))
        point_size = min(sizes)[2]
        base_face = face(ttf, point_size, weight, axes)
        glyphs = []
        for g in logical:
            raster, bearing = ink(base_face, chr(g["codepoint"]))
            glyphs.append({"codepoint":g["codepoint"], "native_metrics":g,
                           "visual_logical_box":[(g["width"]-raster.width)//2,
                               native_baseline+bearing[1]-g["top"], raster.width, raster.height],
                           "source_rects":[]})
        density_sets=[]
        for scale in SCALES:
            density_size=max(1,(point_size*scale+50)//100)
            density_face=face(ttf,density_size,weight,axes)
            cells=[]
            for glyph in glyphs:
                raster, _ = ink(density_face,chr(glyph["codepoint"]))
                cells.append(raster)  # no resizing at all
            atlas,rects=pack(cells)
            relative=f"base/ui-hd/fonts/roboto-{stem}-{scale}.png"
            path=output/relative;path.parent.mkdir(parents=True,exist_ok=True)
            atlas.save(path,optimize=False,compress_level=9)
            for glyph,rect in zip(glyphs,rects):
                if min(rect[:2])<2 or rect[0]+rect[2]+2>atlas.width or rect[1]+rect[3]+2>atlas.height:
                    raise ValueError("Source glyph leaves atlas")
                glyph["source_rects"].append(rect)
            asset={"path":relative,"sha256":sha(path),"bytes":path.stat().st_size,
                   "width":atlas.width,"height":atlas.height,"scale":scale,"font":stem}
            assets.append(asset);density_sets.append(asset)
        overhangs=[g["codepoint"] for g in glyphs if g["visual_logical_box"][0]<0 or
                   g["visual_logical_box"][0]+g["visual_logical_box"][2]>g["native_metrics"]["width"]]
        fonts.append({"font":stem,"original_xml_sha256":sha(original_path),
                      "logical_line_metrics":{n:int(tree.attrib[n]) for n in ("width","height")},
                      "native_extra_spacing":prior_contract["native_extra_spacing"],
                      "native_space_advance":5,"native_extra_line_spacing":2,
                      "native_cap_height":cap_height,"native_baseline":native_baseline,
                      "uniform_font_pixel_size_100":point_size,"weight":weight,
                      "optical_overhang_codepoints":overhangs,"glyphs":glyphs,"density_sets":density_sets})
    license_source=sources/candidate["id"]/"OFL.txt"
    license_target=output/"base/ui-hd/licenses/RobotoCondensed-OFL.txt"
    license_target.parent.mkdir(parents=True,exist_ok=True)
    license_target.write_bytes(license_source.read_bytes())
    assets.append({"path":"base/ui-hd/licenses/RobotoCondensed-OFL.txt","sha256":sha(license_target),
                   "bytes":license_target.stat().st_size})
    manifest={"schema":1,"result":"PASS","family":"Roboto Condensed","scales":list(SCALES),
              "selected_ttf_sha256":sha(ttf),"source_manifest_sha256":sha(sources/"candidates.json"),
              "builder_sha256":sha(Path(__file__)),"assets":assets,"fonts":fonts,
              "logical_metrics_changed":False,"per_glyph_raster_resizing":False,
              "physical_font_snapping_required":True,"native_adapter_required":True,
              "limits":["Native pen advances and line heights stay original; optical overhang is permitted.",
                        "Original kerning/formatting and unknown Unicode fallback stay native."]}
    write_json(output/"manifest.json",manifest)
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=ROOT/"reports/ui-hd-assets/selected-fonts")
    args=parser.parse_args();m=build(args.output)
    print(json.dumps({"result":m["result"],"font_roles":len(m["fonts"]),"assets":len(m["assets"]),
                      "manifest_sha256":sha(args.output/"manifest.json")}))


if __name__=="__main__":main()
