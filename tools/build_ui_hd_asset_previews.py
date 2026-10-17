"""Compose repeatable font/icon concepts, never client or hosting assets.

Fonts are rendered from the original TTF at each physical size. Icons are
cropped from immutable four-by-four RGBA masters in memory and resampled
directly from those source crops. This does not export a runtime atlas.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFont, __version__ as PILLOW_VERSION

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports/ui-hd-assets"
sys.path.insert(0, str(REPORTS / "fonts/_validation-deps"))
from fontTools.ttLib import TTFont
import fontTools

ICON_ORDER = (
    ("map", "Карта"), ("soldier", "Боец"), ("crates", "Склад"),
    ("money", "Торговля"), ("info", "Информация"), ("rifle", "Оружие"),
    ("skills", "Навыки"), ("squad", "Отряд"), ("handshake", "Сделка"),
    ("search", "Поиск"), ("refresh", "Обновить"), ("settings", "Настройки"),
    ("check", "Применить"), ("left", "Назад"), ("right", "Вперёд"),
    ("close", "Закрыть"),
)
SCALES = ((100, 13, 40, 56), (125, 16, 50, 66),
          (150, 20, 60, 76), (200, 26, 80, 96))
BACKGROUND = "#10150f"
FOREGROUND = "#e2e4d2"
MUTED = "#aab39c"
PANEL = "#172016"
PANEL_DARK = "#111910"
BOARD_SIZE = (1800, 1480)
COLUMN_WIDTH = 548


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def evidence(path):
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": sha(raw)}


@dataclass
class FontSource:
    family: str
    path: Path
    digest: str
    axes: tuple
    cmap: frozenset

    def load(self, pixels, weight):
        font = ImageFont.truetype(str(self.path), pixels,
                                  layout_engine=ImageFont.Layout.BASIC)
        values = [14 if tag == "opsz" else weight if tag == "wght" else default
                  for tag, default in self.axes]
        font.set_variation_by_axes(values)
        return font, values


def load_fonts(manifest_path):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    require(manifest["result"] == "PASS", "Font candidates must be validated")
    result = {}
    for candidate in manifest["candidates"]:
        item = candidate["ttf"]
        path = Path(item["path"]).resolve()
        require(path.is_relative_to((REPORTS / "fonts").resolve()),
                "Font source must remain in the font candidate directory")
        require(path.stat().st_size == item["bytes"] and sha(path.read_bytes()) == item["sha256"],
                "Reviewed original TTF differs: " + candidate["family"])
        require(candidate["license"] == "OFL-1.1", "Unexpected font license")
        license_path = path.parent / "OFL.txt"
        reviewed_license = next(x for x in candidate["files"] if x["filename"] == "OFL.txt")
        require(sha(license_path.read_bytes()) == reviewed_license["sha256"],
                "Original OFL license differs")
        with TTFont(path, checkChecksums=2) as tt:
            axes = tuple((a.axisTag, a.defaultValue) for a in tt["fvar"].axes)
            cmap = frozenset(tt.getBestCmap())
        result[candidate["family"]] = FontSource(candidate["family"], path,
                                                item["sha256"], axes, cmap)
    require(set(result) == {"Inter", "Roboto Condensed", "Exo 2"}, "Exact three fonts required")
    return result, manifest


class IconMaster:
    def __init__(self, path):
        self.path = path.resolve()
        require(self.path.is_relative_to((REPORTS / "icons/source").resolve()),
                "Only the concept master source directory is permitted")
        self.original = evidence(self.path)
        with Image.open(self.path) as image:
            image.load()
            require(image.mode == "RGBA", "Master must be RGBA: " + str(path))
            require(image.width == image.height and image.width >= 1024,
                    "Expected a high-resolution square master")
            self.image = image.copy()
        alpha = self.image.getchannel("A")
        require(alpha.getextrema() == (0, 255), "Master must contain actual transparency")
        w, h = self.image.size
        xs = [round(i * w / 4) for i in range(5)]
        ys = [round(i * h / 4) for i in range(5)]
        self.icons = []
        self.crops = []
        for index, (semantic, label) in enumerate(ICON_ORDER):
            row, col = divmod(index, 4)
            cell_box = (xs[col], ys[row], xs[col + 1], ys[row + 1])
            cell = self.image.crop(cell_box)
            bbox = cell.getchannel("A").point(lambda a: 255 if a > 16 else 0).getbbox()
            require(bbox is not None, "Empty icon: " + semantic)
            crop = cell.crop(bbox)
            require(min(crop.size) >= 24, "Unexpected tiny source crop: " + semantic)
            self.icons.append(crop)
            self.crops.append({"index": index, "semantic": semantic, "label_ru": label,
                               "cell": list(cell_box), "alpha_threshold": 16,
                               "bbox_within_cell": list(bbox), "crop_size": list(crop.size),
                               "crop_rgba_sha256": sha(crop.tobytes()),
                               "touches_cell_edge": (bbox[0] == 0 or bbox[1] == 0 or
                                                     bbox[2] == cell.width or bbox[3] == cell.height)})

    def at_size(self, index, optical_size):
        original = self.icons[index]
        ratio = optical_size / max(original.size)
        dimensions = tuple(max(1, round(n * ratio)) for n in original.size)
        # Pillow's RGBA resampler uses premultiplied alpha internally. Every
        # request starts from the original crop, never from the 100% output.
        result = original.resize(dimensions, Image.Resampling.LANCZOS)
        require(max(result.size) == optical_size, "Optical normalization differs")
        return result


@dataclass
class Variant:
    key: str
    title: str
    font: FontSource
    master: IconMaster
    accent: str
    subtitle: str
    source_kind: str


class Painter:
    def __init__(self, size, label):
        self.image = Image.new("RGBA", size, BACKGROUND)
        self.draw = ImageDraw.Draw(self.image)
        self.label = label
        self.text_proof = []
        self.icon_proof = []

    def rectangle(self, box, fill=PANEL, outline=None, width=1, radius=0):
        require(0 <= box[0] < box[2] <= self.image.width and
                0 <= box[1] < box[3] <= self.image.height, "Panel exceeds board bounds")
        if radius:
            self.draw.rounded_rectangle(box, radius, fill=fill, outline=outline, width=width)
        else:
            self.draw.rectangle(box, fill=fill, outline=outline, width=width)

    def text(self, xy, text, source, pixels, weight=400, color=FOREGROUND,
             available_width=None, available_height=None, centered=False):
        require(all(ord(c) in source.cmap for c in text),
                "A preview string requires a missing font glyph: " + text)
        font, axes = source.load(pixels, weight)
        bbox = font.getbbox(text)
        width, height = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x, y = xy
        if available_width is not None:
            require(width <= available_width, "Text clipped horizontally: " + text)
            if centered:
                x += (available_width - width) // 2
        if available_height is not None:
            require(height <= available_height, "Text clipped vertically: " + text)
        require(0 <= x and 0 <= y and x + width <= self.image.width and
                y + height <= self.image.height, "Text exceeds board bounds: " + text)
        mask = font.getmask(text)
        require(mask.getbbox() is not None, "Empty rendered label")
        self.draw.text((x - bbox[0], y - bbox[1]), text, font=font, fill=color)
        self.text_proof.append({"text": text, "family": source.family,
                                "original_ttf_sha256": source.digest,
                                "physical_pixels": pixels, "weight": weight, "axes": axes,
                                "ink_box": [x, y, x + width, y + height],
                                "available_width": available_width,
                                "available_height": available_height,
                                "glyph_mask_sha256": sha(bytes(mask)),
                                "drawn_from_ttf": True, "fits": True})

    def icon(self, variant, index, center, optical_size):
        icon = variant.master.at_size(index, optical_size)
        x = round(center[0] - icon.width / 2)
        y = round(center[1] - icon.height / 2)
        require(0 <= x and 0 <= y and x + icon.width <= self.image.width and
                y + icon.height <= self.image.height, "Icon exceeds board bounds")
        self.image.alpha_composite(icon, (x, y))
        self.icon_proof.append({"variant": variant.key, "semantic": ICON_ORDER[index][0],
                                "optical_max_pixels": optical_size, "dimensions": list(icon.size),
                                "output_box": [x, y, x + icon.width, y + icon.height],
                                "normalized_rgba_sha256": sha(icon.tobytes()),
                                "rendered_directly_from_master_crop": True,
                                "resampled_from_100_percent_bitmap": False})

    def png(self):
        stream = BytesIO()
        self.image.convert("RGB").save(stream, format="PNG", optimize=False,
                                       compress_level=9)
        return stream.getvalue()


def render_game_panel(p, v, x):
    f = v.font
    p.rectangle((x + 22, 654, x + 526, 870), fill=PANEL_DARK, outline="#4a593f")
    p.text((x + 38, 666), "Инвентарь", f, 23, 600, v.accent, 420, 29)
    for i, label in enumerate(("Снаряжение", "Навыки", "Экран")):
        left = x + 38 + 156 * i
        p.rectangle((left, 706, left + 148, 739), fill="#2b3825" if i == 0 else "#1d2919",
                    outline=v.accent if i == 0 else "#3e4d34", radius=3)
        p.text((left + 7, 714), label, f, 18, 500, available_width=134, available_height=20,
               centered=True)
    p.icon(v, 1, (x + 62, 767), 40)
    p.text((x + 94, 749), "Тактический жилет", f, 18, 500, available_width=410, available_height=24)
    p.text((x + 94, 775), "Броня: 80%   Прочность: 63", f, 16, 400, MUTED, 410, 21)
    p.draw.line((x + 38, 804, x + 510, 804), fill="#35452d", width=1)
    p.icon(v, 5, (x + 62, 834), 40)
    p.text((x + 94, 813), "Штурмовая винтовка", f, 18, 500, available_width=410, available_height=24)
    p.text((x + 94, 840), "Урон: 24   Патроны: 50", f, 16, 400, MUTED, 410, 21)
    p.rectangle((x + 22, 891, x + 526, 1020), fill=PANEL_DARK, outline="#4a593f")
    p.text((x + 38, 903), "Глобальный  ·  Локация", f, 17, 600, v.accent, 460, 23)
    p.text((x + 38, 935), "Резервист: Готов к выходу.", f, 17, 400, available_width=460, available_height=24)
    p.text((x + 38, 963), "Отряд: Держим правый фланг.", f, 17, 400, MUTED, 460, 24)


def render_column(p, v, x):
    f = v.font
    p.rectangle((x, 170, x + COLUMN_WIDTH, 1420), outline=v.accent, radius=8)
    p.text((x + 22, 190), v.title, f, 30, 600, v.accent, 504, 39)
    p.text((x + 22, 234), v.font.family + " · OFL-1.1", f, 18, 500, available_width=504, available_height=24)
    p.text((x + 22, 260), v.subtitle, f, 15, 400, MUTED, 504, 21)
    for index, (_, label) in enumerate(ICON_ORDER):
        row, col = divmod(index, 4)
        left, top = x + 22 + 126 * col, 296 + 84 * row
        p.icon(v, index, (left + 63, top + 28), 56)
        p.text((left, top + 62), label, f, 14, 500, available_width=126,
               available_height=20, centered=True)
    p.draw.line((x + 22, 639, x + 526, 639), fill="#4a593f", width=1)
    render_game_panel(p, v, x)
    p.text((x + 22, 1043), "МАСШТАБЫ", f, 19, 600, v.accent, 504, 26)
    p.text((x + 22, 1071), "13 логических px · каждый размер заново", f, 14, 400, MUTED, 504, 21)
    top = 1100
    for percent, pixels, icon_pixels, height in SCALES:
        p.rectangle((x + 22, top, x + 526, top + height - 4), fill="#1b2818", outline="#36482d")
        p.text((x + 34, top + 12), str(percent) + "%", f, 17, 600, v.accent, 72, 24)
        p.text((x + 34, top + 35), str(pixels) + " px", f, 12, 400, MUTED, 72, 17)
        p.icon(v, 1, (x + 151, top + (height - 4) / 2), icon_pixels)
        p.text((x + 214, top + (height - pixels) // 2 - 2), "Броня: 80%", f, pixels, 500,
               available_width=290, available_height=height - 10)
        top += height


def main_board(variants, fonts, provisional):
    p = Painter(BOARD_SIZE, "variants-comparison")
    p.text((40, 28), "ШРИФТЫ И ИКОНКИ", fonts["Inter"], 42, 600, available_width=1718, available_height=55)
    p.text((42, 91), "Концепты. Не скриншоты игры.", fonts["Inter"], 25, 500, "#d3dcbf", 1716, 35)
    p.text((42, 132), "Три оформления · реальные TTF · размеры 100–200%" +
           (" · предварительные masters" if provisional else ""),
           fonts["Inter"], 17, 400, MUTED, 1716, 23)
    for x, variant in zip((40, 626, 1212), variants):
        render_column(p, variant, x)
    p.text((42, 1441), "16 символов для выбора оформления. Плотность UI показана отдельно от разрешения игрового мира.",
           fonts["Inter"], 16, 400, MUTED, 1716, 23)
    return p


def individual_board(variant, fonts, provisional):
    p = Painter((600, 1480), variant.key)
    p.text((26, 34), "Оформление " + variant.key.upper(), fonts["Inter"], 30, 600, available_width=548, available_height=42)
    p.text((26, 88), "Концепт. Не скриншот игры.", fonts["Inter"], 20, 500, MUTED, 548, 29)
    p.text((26, 126), "Исходники и TTF для выбора" + (" · draft" if provisional else ""),
           fonts["Inter"], 16, 400, MUTED, 548, 23)
    render_column(p, variant, 26)
    p.text((26, 1441), "Реальные шрифты. В клиент пока не встроено.", fonts["Inter"], 15, 400, MUTED, 548, 22)
    return p


def scale_board(variants, fonts):
    p = Painter((1800, 1080), "scale-review")
    p.text((40, 30), "МАСШТАБ: ЧЕТЫРЕ ОТДЕЛЬНЫХ РЕНДЕРА", fonts["Inter"], 34, 600,
           available_width=1718, available_height=45)
    p.text((42, 89), "Концепты. Не скриншоты игры. Один текст — четыре физических размера.",
           fonts["Inter"], 22, 500, MUTED, 1716, 32)
    for x, v in zip((40, 626, 1212), variants):
        p.rectangle((x, 150, x + COLUMN_WIDTH, 990), outline=v.accent, radius=8)
        p.text((x + 22, 171), v.title, v.font, 26, 600, v.accent, 504, 35)
        p.text((x + 22, 215), v.font.family, v.font, 20, 500, available_width=504, available_height=28)
        top = 280
        for (percent, pixels, icon_pixels, _), height in zip(SCALES, (130, 146, 166, 188)):
            p.rectangle((x + 22, top, x + 526, top + height - 12), fill=PANEL_DARK, outline="#405438")
            p.text((x + 38, top + 13), f"{percent}% · текст {pixels} px · значок {icon_pixels} px",
                   v.font, 15, 500, v.accent, 472, 23)
            p.icon(v, 1, (x + 82, top + 42 + (height - 55) / 2), icon_pixels)
            p.text((x + 155, top + 52), "Снаряжение", v.font, pixels, 600,
                   available_width=349, available_height=40)
            p.text((x + 155, top + 58 + pixels), "Броня: 80%", v.font, pixels, 400, MUTED, 349, 40)
            top += height
    p.text((42, 1028), "Каждый значок взят из master; каждый текст заново построен из TTF. Изображение 100% не увеличивается.",
           fonts["Inter"], 16, 400, MUTED, 1716, 24)
    return p


def compose(variants, fonts, provisional):
    return {"variants-comparison.png": main_board(variants, fonts, provisional),
            **{v.key + ".png": individual_board(v, fonts, provisional) for v in variants},
            "scale-review.png": scale_board(variants, fonts)}


def build(args):
    output = (args.output or REPORTS / ("previews-provisional" if args.provisional else "previews")).resolve()
    require(output.is_relative_to(REPORTS.resolve()) and output != REPORTS.resolve(),
            "Outputs must stay below reports/ui-hd-assets")
    require(not any(p.is_symlink() for p in [output, *output.parents]), "Output symlinks are not permitted")
    fonts, font_manifest = load_fonts(args.font_manifest.resolve())
    masters = [IconMaster(p) for p in (args.master_a, args.master_b, args.master_c)]
    vector_b = masters[1].path.name == "b-tactical-vector.png"
    vector_evidence = None
    if vector_b:
        source_manifest_path = REPORTS / "icons/vector-b/manifest.json"
        source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
        require(source_manifest["generated_from_geometry"] and
                not source_manifest["traced_from_raster"], "Vector source identity differs")
        require(source_manifest["masterRecord"]["sha256"] == masters[1].original["sha256"],
                "Reviewed SVG raster master differs")
        require([s["name"] for s in source_manifest["symbols"]] ==
                [name for name, _ in ICON_ORDER], "SVG semantic order differs")
        svg_files = []
        for symbol in source_manifest["symbols"]:
            svg_path = Path(symbol["source"]["file"]).resolve()
            require(svg_path.is_relative_to((REPORTS / "icons/vector-b/svg").resolve()),
                    "SVG source path exceeds its source directory")
            actual = evidence(svg_path)
            require(actual["sha256"] == symbol["source"]["sha256"] and
                    actual["bytes"] == symbol["source"]["bytes"], "Original SVG differs")
            svg_files.append({"semantic": symbol["name"], **actual})
        vector_evidence = {"manifest": evidence(source_manifest_path), "original_svg_files": svg_files,
                           "master_matches_source_manifest": True,
                           "generated_from_geometry": True, "traced_from_raster": False}
    variants = [Variant("a", "A · Классика HD", fonts["Exo 2"], masters[0], "#c6ae76", "Бронза и геометричные буквы", "imagegen_raster"),
                Variant("b", "B · Тактика", fonts["Roboto Condensed"], masters[1], "#c8d79e",
                        "SVG-значки · компактные подписи" if vector_b else "Компактные технические подписи",
                        "original_svg_geometry_rendered_to_RGBA" if vector_b else "imagegen_raster"),
                Variant("c", "C · Эмаль", fonts["Inter"], masters[2], "#bbcdbd", "Контрастные значки и спокойный текст", "imagegen_raster")]
    first = compose(variants, fonts, args.provisional)
    second = compose(variants, fonts, args.provisional)
    bytes_by_name = {name: painter.png() for name, painter in first.items()}
    require(all(raw == second[name].png() for name, raw in bytes_by_name.items()),
            "Repeated font/icon composition produced different PNG bytes")
    require(all(evidence(m.path) == m.original for m in masters), "A master changed during composition")
    require(all(sha(f.path.read_bytes()) == f.digest for f in fonts.values()), "An original TTF changed")
    output.mkdir(parents=True, exist_ok=True)
    outputs = []
    for name, raw in bytes_by_name.items():
        path = output / name
        require(not path.is_symlink(), "Output file symlink is not permitted")
        path.write_bytes(raw)
        with Image.open(path) as check:
            check.load()
            require(check.size == first[name].image.size and check.mode == "RGB", "Saved PNG verification failed")
        painter = first[name]
        outputs.append({**evidence(path), "dimensions": list(painter.image.size),
                        "text_draws": len(painter.text_proof), "icon_draws": len(painter.icon_proof),
                        "all_text_fits": True, "all_icons_fit": True,
                        "fresh_TTF_text_proof": painter.text_proof,
                        "independent_master_size_proof": painter.icon_proof})
    manifest = {"schema": 1, "result": "PASS", "provisional_sources": args.provisional,
                "concepts_not_game_screenshots": True, "pipeline_sha256": sha(Path(__file__).read_bytes()),
                "font_manifest": evidence(args.font_manifest.resolve()),
                "font_source_modified": False, "masters_modified": False,
                "runtime_atlas_exported": False, "client_modified": False,
                "hosting_modified": False, "system_fonts_installed": False,
                "repeat_same_PNG_bytes": True,
                "environment": {"python": sys.version.split()[0], "pillow": PILLOW_VERSION,
                                "fonttools": fontTools.__version__, "Pillow_layout_engine": "BASIC"},
                "variants": [{"id": v.key, "title": v.title, "actual_font_family": v.font.family,
                              "original_TTF": evidence(v.font.path), "font_license": "OFL-1.1",
                              "icon_source_kind": v.source_kind,
                              "master": v.master.original, "source_dimensions": list(v.master.image.size),
                              "icon_crops": v.master.crops} for v in variants],
                "scale_samples": [{"percent": a, "font_physical_pixels": b, "icon_optical_pixels": c,
                                   "font_logical_reference_pixels": 13} for a, b, c, _ in SCALES],
                "icon_count_per_variant": 16, "comparison_grid_optical_pixels": 56,
                "vector_b_source_evidence": vector_evidence,
                "recommendation": {"variant": "b", "reason": "Roboto Condensed permits compact labels; selection remains with the user"},
                "limits": ["Concept icon families do not establish exact native toolbar mapping",
                           "Skills is a proposed symbol, not a verified native toolbar replacement",
                           "Preview logical reference and actual client atlas integration are separate",
                           "Game resolution, world picking and GUI behavior are not tested by these boards"],
                "outputs": outputs}
    path = output / "preview-manifest.json"
    require(not path.is_symlink(), "Manifest output symlink is not permitted")
    path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return {"result": "PASS", "manifest": str(path), "outputs": [str(output / name) for name in first],
            "repeat_same_PNG_bytes": True, "provisional": args.provisional,
            "source_mutations": 0, "client_or_hosting_changes": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--master-a", type=Path, default=REPORTS / "icons/source/a-classic-hd-clean.png")
    parser.add_argument("--master-b", type=Path, default=REPORTS / "icons/source/b-tactical-vector.png")
    parser.add_argument("--master-c", type=Path, default=REPORTS / "icons/source/c-enamel-clean.png")
    parser.add_argument("--font-manifest", type=Path, default=REPORTS / "fonts/candidates.json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--provisional", action="store_true", help="Label provisional inputs and default to a separate output folder")
    args = parser.parse_args()
    print(json.dumps(build(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
