"""Pack the selected ImageGen city masters into separate native UI textures.

This is an offline format compiler: it crops, aligns, resamples and packs the
approved pixels. It does not repaint, recolour, synthesize states or bake labels.
All native shared resources and installed clients are outside this tool's scope.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets" / "contracts-city-ui-v1"
SOURCE = ASSETS / "textures" / "masters-field-hq.png"
OUTPUT = ASSETS / "runtime"
REPORT = ROOT / "reports" / "contracts-local" / "city-ui" / "assets"
MANIFEST = ASSETS / "runtime-manifest.json"
SOURCE_SHA256 = "56f22a26ab65f0f17878340ba852a6644724b4cd139a0fdbfbc19c570bdd7cac"
STATE_ORDER = ("normal", "disabled", "pressed", "hover")

# Regions are disjoint. Alpha >=16 excludes diffuse near-zero canvas residue,
# but the actual crop retains all alpha and colour bytes within its bounds.
# These fixed bounds are guarded against the pinned original before packing.
SOURCE_SPEC = {
    "schema": 1,
    "source": "textures/masters-field-hq.png",
    "sha256": SOURCE_SHA256,
    "dimensions": [1536, 1024],
    "mode": "RGBA",
    "bounds_alpha_threshold": 16,
    "state_order": list(STATE_ORDER),
    "pieces": {
        "normal": {"region": [0, 0, 952, 291], "bounds": [46, 81, 940, 274]},
        "disabled": {"region": [0, 291, 952, 507], "bounds": [46, 301, 940, 496]},
        "pressed": {"region": [0, 507, 952, 735], "bounds": [46, 521, 939, 717]},
        "hover": {"region": [0, 735, 952, 1024], "bounds": [46, 741, 941, 939]},
        "frame": {"region": [953, 0, 1536, 731], "bounds": [962, 66, 1483, 711]},
        "contracts_icon": {"region": [999, 732, 1245, 982], "bounds": [1040, 739, 1214, 942]},
        "group_icon": {"region": [1246, 737, 1536, 985], "bounds": [1265, 776, 1458, 922]},
    },
    "button": {
        "canonical_dimensions": [896, 200],
        "cap_source_width": 200,
        "middle_source_column": 448,
        "atlas_dimensions": [100, 100],
        "cell": 25,
        "columns": ["left", "repeating-middle", "right", "unused-transparent"],
    },
    "frame": {
        "atlas_dimensions": [128, 128],
        "cell": 32,
        "cap_source_width": 70,
        "top_source_height": 100,
        "bottom_source_height": 70,
        "unused_row_and_column": "transparent",
        "centre": "transparent source opening",
    },
    "icons": {"canvas": [32, 32], "preserve_aspect": True},
    "operations": ["alpha-bound crop", "Lanczos resampling", "native slice packing"],
    "baked_labels": False,
    "artistic_pixel_edits": False,
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verified_source(path: Path) -> Image.Image:
    if sha256(path) != SOURCE_SHA256:
        raise ValueError("City UI master differs from the approved immutable ImageGen source")
    with Image.open(path) as original:
        if original.size != tuple(SOURCE_SPEC["dimensions"]) or original.mode != "RGBA":
            raise ValueError("City UI master dimensions or alpha mode differ")
        image = original.copy()
    for name, piece in SOURCE_SPEC["pieces"].items():
        region = tuple(piece["region"])
        local = image.crop(region).getchannel("A").point(lambda alpha: 255 if alpha >= 16 else 0).getbbox()
        if local is None:
            raise ValueError(f"Empty source region: {name}")
        bounds = [local[0] + region[0], local[1] + region[1], local[2] + region[0], local[3] + region[1]]
        if bounds != piece["bounds"]:
            raise ValueError(f"Source slice geometry changed: {name}")
    return image


def source_piece(image: Image.Image, name: str) -> Image.Image:
    return image.crop(tuple(SOURCE_SPEC["pieces"][name]["bounds"]))


def pack_button(states: list[Image.Image], cell: int = 25) -> Image.Image:
    """Keep each source state; repeat a centre column without horizontal seams."""
    if len(states) != 4 or cell < 1:
        raise ValueError("Native button needs four states and a positive cell size")
    result = Image.new("RGBA", (cell * 4, cell * 4))
    width, height = SOURCE_SPEC["button"]["canonical_dimensions"]
    cap = SOURCE_SPEC["button"]["cap_source_width"]
    mid = SOURCE_SPEC["button"]["middle_source_column"]
    for row, state in enumerate(states):
        source = state.convert("RGBA").resize((width, height), Image.Resampling.LANCZOS)
        slices = [source.crop((0, 0, cap, height)), source.crop((mid, 0, mid + 1, height)), source.crop((width - cap, 0, width, height))]
        for column, piece in enumerate(slices):
            result.paste(piece.resize((cell, cell), Image.Resampling.LANCZOS), (column * cell, row * cell))
    return result


def pack_frame(frame: Image.Image, cell: int = 32) -> Image.Image:
    """Pack the source opening and border using native 0,1,2/4,5,6/8,9,10."""
    frame = frame.convert("RGBA")
    width, height = frame.size
    cap = SOURCE_SPEC["frame"]["cap_source_width"]
    top = SOURCE_SPEC["frame"]["top_source_height"]
    bottom = SOURCE_SPEC["frame"]["bottom_source_height"]
    if width < 2 * cap + 1 or height < top + bottom + 1 or cell < 1:
        raise ValueError("Frame source is too small for the approved native slices")
    xs = [(0, cap), (width // 2, width // 2 + 1), (width - cap, width)]
    ys = [(0, top), (height // 2, height // 2 + 1), (height - bottom, height)]
    result = Image.new("RGBA", (cell * 4, cell * 4))
    for row, (y0, y1) in enumerate(ys):
        for column, (x0, x1) in enumerate(xs):
            piece = frame.crop((x0, y0, x1, y1)).resize((cell, cell), Image.Resampling.LANCZOS)
            result.paste(piece, (column * cell, row * cell))
    return result


def pack_icon(icon: Image.Image, cell: int = 32) -> Image.Image:
    if cell < 1:
        raise ValueError("Icon canvas must be positive")
    icon = icon.convert("RGBA")
    icon.thumbnail((cell, cell), Image.Resampling.LANCZOS)
    result = Image.new("RGBA", (cell, cell))
    result.paste(icon, ((cell - icon.width) // 2, (cell - icon.height) // 2))
    return result


def assemble_button(atlas: Image.Image, size: tuple[int, int], state: int) -> Image.Image:
    """Render exactly the repeating native three-slice layout for QA."""
    cell = atlas.width // 4
    width, height = size
    if atlas.size != (cell * 4, cell * 4) or not 0 <= state < 4 or width < 2 * cell or height < 1:
        raise ValueError("Invalid native button assembly")
    result = Image.new("RGBA", size)
    y = state * cell
    result.paste(atlas.crop((0, y, cell, y + cell)).resize((cell, height)), (0, 0))
    middle = atlas.crop((cell, y, cell * 2, y + cell)).resize((cell, height))
    x = cell
    while x < width - cell:
        span = min(cell, width - cell - x)
        result.paste(middle.crop((0, 0, span, height)), (x, 0))
        x += span
    result.paste(atlas.crop((cell * 2, y, cell * 3, y + cell)).resize((cell, height)), (width - cell, 0))
    return result


def assemble_frame(atlas: Image.Image, size: tuple[int, int]) -> Image.Image:
    cell = atlas.width // 4
    width, height = size
    if atlas.size != (cell * 4, cell * 4) or width < cell * 2 or height < cell * 2:
        raise ValueError("Invalid native frame assembly")
    result = Image.new("RGBA", size)
    xs = [(0, cell), (cell, width - cell), (width - cell, width)]
    ys = [(0, cell), (cell, height - cell), (height - cell, height)]
    for row, (y0, y1) in enumerate(ys):
        for column, (x0, x1) in enumerate(xs):
            piece = atlas.crop((column * cell, row * cell, (column + 1) * cell, (row + 1) * cell))
            result.paste(piece.resize((x1 - x0, y1 - y0)), (x0, y0))
    return result


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_native_preview(report: Path, output: Path) -> None:
    """HTML/canvas reference uses the exact packed slices, with live captions."""
    import os
    base = Path(os.path.relpath(output / "base" / "pda", report)).as_posix()
    html = """<!doctype html>
<html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Полевой штаб — проверка нативных текстур</title>
<style>
*{box-sizing:border-box}body{margin:0;padding:28px;background:#171b18;color:#e6e4d8;font:14px/1.5 "Segoe UI",sans-serif}
main{max-width:1080px;margin:auto}h1{font-size:24px;margin:0 0 12px}p{max-width:900px;color:#aeb7ab}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:24px}.card{background:#222723;padding:18px;border:1px solid #685338;border-radius:5px}
.checker{background-color:#384139;background-image:linear-gradient(45deg,#2c332c 25%,transparent 25%),linear-gradient(-45deg,#2c332c 25%,transparent 25%),linear-gradient(45deg,transparent 75%,#2c332c 75%),linear-gradient(-45deg,transparent 75%,#2c332c 75%);background-size:16px 16px;background-position:0 0,0 8px,8px -8px,-8px 0}
canvas{display:block;max-width:100%}.state{margin:12px 0 5px;color:#c6b189}.icons{display:flex;gap:20px;align-items:center;padding:14px}.icons img{width:32px;height:32px}.atlas{display:flex;gap:25px;padding:16px}.atlas img{image-rendering:pixelated}
button{background:#303b30;color:#e6e4d8;border:1px solid #968164;padding:7px 14px;cursor:pointer}button:focus-visible{outline:2px solid #ffc249}a{color:#c5a977}
@media(max-width:720px){body{padding:14px}.grid{grid-template-columns:1fr}}
</style><main><h1>«Полевой штаб»: срезы для настоящего клиента</h1>
<p>Показаны ресурсы из упакованных PNG, а не макет города. Надписи рисуются отдельно в canvas. Эта проверка геометрии и прозрачности не заменяет проверку игрового клиента.</p>
<div class="grid"><section class="card"><strong>100×100: строки normal / disabled / pressed / hover</strong>
<div class="state">Обычная</div><canvas class="checker" data-state="0" width="224" height="25"></canvas>
<div class="state">Недоступная</div><canvas class="checker" data-state="1" width="224" height="25"></canvas>
<div class="state">Нажатая</div><canvas class="checker" data-state="2" width="224" height="25"></canvas>
<div class="state">Под курсором</div><canvas class="checker" data-state="3" width="224" height="25"></canvas>
<div class="state">Ширина 360, высота 32</div><canvas class="checker" data-state="0" data-label="Группа" width="360" height="32"></canvas>
<div class="state">Интерактивная проверка: движение мыши, нажатие, выход</div><canvas id="interactive" class="checker" tabindex="0" role="button" aria-label="Проверка состояния кнопки Контракты" width="224" height="25"></canvas>
</section><section class="card"><strong>128×128: рамка из девяти срезов</strong>
<div class="state">Рамка 320×224, прозрачное содержимое</div><canvas id="frame" class="checker" width="320" height="224"></canvas>
<div class="state">Отдельные значки 32×32</div><div class="icons checker"><img src="BASE/contracts_icon.png" alt="Контракты"><span>Контракты</span><img src="BASE/group_icon.png" alt="Группа"><span>Группа</span></div>
</section></div>
<div class="card" style="margin-top:24px"><strong>Исходные нативные атласы, масштаб 1:1</strong><div class="atlas checker"><img src="BASE/contracts_button.png" alt="Атлас кнопки" width="100" height="100"><img src="BASE/contracts_frame.png" alt="Атлас рамки" width="128" height="128"></div></div>
<p id="result">Загрузка местных PNG…</p></main><script>
const load=p=>new Promise((ok,no)=>{const i=new Image;i.onload=()=>ok(i);i.onerror=()=>no(Error(p));i.src=p});
let button,frame;let interactiveState=0;
function drawButton(canvas,state,label='Контракты'){const c=canvas.getContext('2d'),w=canvas.width,h=canvas.height;c.clearRect(0,0,w,h);c.drawImage(button,0,state*25,25,25,0,0,25,h);for(let x=25;x<w-25;x+=25){const span=Math.min(25,w-25-x);c.drawImage(button,25,state*25,span,25,x,0,span,h)}c.drawImage(button,50,state*25,25,25,w-25,0,25,h);c.fillStyle=state===1?'#9c9b91':'#eee9cd';c.font='13px Segoe UI';c.textAlign='center';c.textBaseline='middle';c.fillText(label,w/2,h/2+(state===2?1:0))}
function drawFrame(canvas){const c=canvas.getContext('2d');const xs=[[0,32],[32,canvas.width-32],[canvas.width-32,canvas.width]],ys=[[0,32],[32,canvas.height-32],[canvas.height-32,canvas.height]];for(let r=0;r<3;r++)for(let n=0;n<3;n++)c.drawImage(frame,n*32,r*32,32,32,xs[n][0],ys[r][0],xs[n][1]-xs[n][0],ys[r][1]-ys[r][0]);c.fillStyle='#eee9cd';c.font='13px Segoe UI';c.textAlign='center';c.fillText('Контракты',canvas.width/2,19)}
(async()=>{[button,frame]=await Promise.all([load('BASE/contracts_button.png'),load('BASE/contracts_frame.png')]);document.querySelectorAll('[data-state]').forEach(c=>drawButton(c,+c.dataset.state,c.dataset.label));drawFrame(document.querySelector('#frame'));const test=document.querySelector('#interactive');const redraw=s=>{interactiveState=s;test.dataset.currentState=String(s);drawButton(test,s)};redraw(0);test.addEventListener('mouseenter',()=>redraw(3));test.addEventListener('mouseleave',()=>redraw(0));test.addEventListener('mousedown',()=>redraw(2));test.addEventListener('mouseup',()=>redraw(3));test.addEventListener('focus',()=>{if(interactiveState!==2)redraw(3)});test.addEventListener('blur',()=>redraw(0));test.addEventListener('keydown',e=>{if(['Enter',' '].includes(e.key)){e.preventDefault();redraw(2)}});test.addEventListener('keyup',e=>{if(['Enter',' '].includes(e.key))redraw(3)});document.querySelector('#result').textContent='Четыре PNG загружены. Подписи остаются отдельным текстом. Общее gui_button не изменено.';window.nativeAssetsReady=true})().catch(e=>document.querySelector('#result').textContent='Ошибка: '+e.message);
</script></html>
"""
    (report / "native-preview.html").write_text(html.replace("BASE/", base + "/"), encoding="utf-8")


def build(source: Path = SOURCE, output: Path = OUTPUT, report: Path = REPORT, manifest: Path = MANIFEST) -> dict:
    image = verified_source(source)  # Reject unexpected sources before writing.
    states = [source_piece(image, name) for name in STATE_ORDER]
    resources = {
        "base/pda/contracts_button.png": pack_button(states),
        "base/pda/contracts_frame.png": pack_frame(source_piece(image, "frame")),
        "base/pda/contracts_icon.png": pack_icon(source_piece(image, "contracts_icon")),
        "base/pda/group_icon.png": pack_icon(source_piece(image, "group_icon")),
    }
    records = []
    for relative, resource in resources.items():
        path = output / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        resource.save(path, "PNG", optimize=False, compress_level=9)
        alpha = resource.getchannel("A")
        records.append({"path": relative, "sha256": sha256(path), "size": path.stat().st_size,
                        "dimensions": list(resource.size), "mode": resource.mode,
                        "alpha_extrema": list(alpha.getextrema()), "new_resource": True,
                        "before_sha256": None, "before_size": None})
    report.mkdir(parents=True, exist_ok=True)
    button = resources["base/pda/contracts_button.png"]
    for state, name in enumerate(STATE_ORDER):
        assemble_button(button, (224, 25), state).save(report / f"button-{name}-native.png")
        assemble_button(button, (360, 32), state).save(report / f"button-{name}-wide.png")
    assemble_frame(resources["base/pda/contracts_frame.png"], (320, 224)).save(report / "frame-native.png")
    write_json(report / "source-spec.json", SOURCE_SPEC)
    write_native_preview(report, output)
    result = {"schema": 1, "variant": "field-hq", "source": SOURCE_SPEC["source"],
              "source_sha256": SOURCE_SHA256, "operations": SOURCE_SPEC["operations"],
              "state_order": list(STATE_ORDER), "native_index_layout": "button:3-slice / frame:9-slice; unused fourth cells transparent",
              "baked_labels": False, "shared_resources_modified": False, "hosted_upload": False,
              "files": records, "qa": {"render": "native sliced raster reference", "real_game_client": False}}
    write_json(manifest, result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--report", type=Path, default=REPORT)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.output, args.report, args.manifest), ensure_ascii=False, indent=2))
