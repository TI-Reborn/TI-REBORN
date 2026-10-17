"""Build compact scale specimens from real TTFs and reviewed icon exports."""
from __future__ import annotations

import base64
import hashlib
from io import BytesIO
import json
from pathlib import Path

from PIL import Image, ImageDraw
from build_ui_hd_asset_previews import load_fonts, REPORTS


VIZ = Path('C:/Users/jundu/.codex/visualizations/2026/10/09/01a12111-628e-7733-988a-b4de287d580d')
PACK = REPORTS / 'icons/candidate-packs-v3'
VARIANTS = {'a': ('a-classic-hd', 'Exo 2'),
            'b': ('b-tactical-clean', 'Roboto Condensed'),
            'c': ('c-enamel', 'Inter')}
SIZES = {100: (13, 40), 125: (16, 50), 150: (20, 60), 200: (26, 80)}
SYMBOLS = ('map', 'squad', 'search')
CANVAS_WIDTH = 320


def sha(data):
    return hashlib.sha256(data).hexdigest()


def build():
    fonts, _ = load_fonts(REPORTS / 'fonts/candidates.json')
    manifest = json.loads((PACK / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest['checks']['PASS']
    assets = {}
    proof = []
    directory = REPORTS / 'previews/specimens'
    directory.mkdir(parents=True, exist_ok=True)
    for variant, (style, family) in VARIANTS.items():
        assets[variant] = {}
        approved = {Path(row['file']).resolve(): row['sha256']
                    for row in manifest['styles'][style]['exports']}
        for scale, (text_size, icon_size) in SIZES.items():
            canvas = Image.new('RGBA', (CANVAS_WIDTH, 210), (20, 30, 17, 255))
            draw = ImageDraw.Draw(canvas)
            face, axes = fonts[family].load(text_size, 500)
            text_boxes = []
            for line, y in [('Броня бойца', 12), ('Защита 80 · Вес 3,2', 26 + text_size)]:
                bounds = draw.textbbox((12, y), line, font=face, anchor='lt')
                assert 0 <= bounds[0] < bounds[2] <= CANVAS_WIDTH - 12
                assert 0 <= bounds[1] < bounds[3] < 118
                draw.text((12, y), line, font=face, anchor='lt', fill=(226, 228, 210, 255))
                text_boxes.append({'text': line, 'bounds': list(bounds)})
            x = (CANVAS_WIDTH - len(SYMBOLS) * icon_size - (len(SYMBOLS) - 1) * 4) // 2
            icon_inputs = []
            for symbol in SYMBOLS:
                path = (PACK / style / str(scale) / 'symbols' / (symbol + '.png')).resolve()
                data = path.read_bytes()
                assert sha(data) == approved[path]
                with Image.open(BytesIO(data)) as source:
                    source.load()
                    assert source.mode == 'RGBA' and source.size == (icon_size, icon_size)
                    canvas.alpha_composite(source, (x, 198 - icon_size))
                icon_inputs.append({'path': str(path), 'sha256': sha(data)})
                x += icon_size + 4
            buffer = BytesIO()
            canvas.convert('RGB').save(buffer, format='PNG', optimize=True)
            data = buffer.getvalue()
            path = directory / (variant + '-' + str(scale) + '.png')
            path.write_bytes(data)
            assets[variant][str(scale)] = 'data:image/png;base64,' + base64.b64encode(data).decode('ascii')
            proof.append({'variant': variant, 'family': family, 'scale': scale,
                          'font_pixels': text_size, 'icon_pixels': icon_size,
                          'font_sha256': fonts[family].digest, 'font_axes': axes,
                          'text_boxes': text_boxes, 'icon_inputs': icon_inputs,
                          'file': str(path), 'sha256': sha(data),
                          'actual_source_rasterization': True,
                          'old_bitmap_upscaled': False})
    template = (VIZ / 'ui-font-icon-options.template.html').read_text(encoding='utf-8')
    assert template.count('__TIO_SPECIMEN_DATA__') == 1
    fragment = template.replace('__TIO_SPECIMEN_DATA__', json.dumps(assets, separators=(',', ':')))
    assert not any(mark in fragment for mark in ('<!doctype', '<html', '<head', '<body', 'fetch(', 'XMLHttpRequest', 'WebSocket'))
    assert len(fragment.encode('utf-8')) < 1_000_000
    assert '\\"' not in fragment and '\\n' not in fragment
    output = VIZ / 'ui-font-icon-options.html'
    output.write_text(fragment, encoding='utf-8')
    report = {'result': 'PASS', 'specimens': proof, 'html': str(output),
              'html_sha256': sha(output.read_bytes()), 'html_bytes': output.stat().st_size,
              'source_pack_manifest_sha256': sha((PACK / 'manifest.json').read_bytes()),
              'interactive_browser_validation': False, 'client_installed': False,
              'published': False}
    (directory / 'proof.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'result': 'PASS', 'html': str(output), 'bytes': output.stat().st_size,
                      'specimens': len(proof)}, ensure_ascii=False))


if __name__ == '__main__':
    build()
