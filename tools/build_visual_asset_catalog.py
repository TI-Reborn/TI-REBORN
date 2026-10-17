"""Read-only visual catalog of original setting textures and model references."""
import hashlib
import html
import io
import json
import re
import struct
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(r'C:\Program Files (x86)\TIOnline\base\setting')
OUT = ROOT / 'reports/asset-catalog'


def decode(raw):
    mode = 'Обычное изображение'
    if raw.startswith(bytes.fromhex('07e181')):
        # ti.exe 666060; called with DX=100 by AJPG_EX loader 6663c8.
        key = 100
        data = bytearray()
        for cipher in raw:
            data.append(cipher ^ (key >> 8))
            key = ((key + cipher) * 0xce6d + 0x58bf) & 65535
        if data[:8] != b'\x07AJPG_EX':
            raise ValueError('Unexpected secure stream header')
        color_size, mask_size = struct.unpack_from('<QQ', data, 39)
        if 55 + color_size + mask_size != len(data):
            raise ValueError('AJPG stream lengths do not match')
        color = Image.open(io.BytesIO(data[55:55 + color_size])).convert('RGBA')
        mask = Image.open(io.BytesIO(data[55 + color_size:])).convert('RGB')
        if color.size != mask.size:
            raise ValueError('AJPG mask dimensions do not match')
        # Native 6661cc averages mask RGB channels; 6662dc writes alpha.
        alpha = bytes((r + g + b) // 3 for r, g, b in zip(*[bytes(c.tobytes()) for c in mask.split()]))
        color.putalpha(Image.frombytes('L', color.size, alpha))
        return color, 'AJPG_EX: цвет + прозрачность'
    image = Image.open(io.BytesIO(raw)).convert('RGBA')
    # Pillow treats the fourth byte of BI_RGB BMP32 as unused and returns RGB.
    # The native game loader uses that byte as alpha for its texture resources.
    if raw.startswith(b'BM') and len(raw) >= 54:
        offset = struct.unpack_from('<I', raw, 10)[0]
        dib_size = struct.unpack_from('<I', raw, 14)[0]
        width, height, planes, bits, compression = struct.unpack_from('<iiHHI', raw, 18)
        if dib_size >= 40 and planes == 1 and bits == 32 and compression == 0:
            stride = width * 4
            if width <= 0 or height == 0 or offset + stride * abs(height) > len(raw):
                raise ValueError('Invalid native BMP32 texture')
            native = Image.frombytes('RGBA', (width, abs(height)), raw[offset:offset + stride * abs(height)],
                                     'raw', 'BGRA', stride, -1 if height > 0 else 1)
            image.putalpha(native.getchannel('A'))
            mode = 'BMP32: color + native alpha'
    return image, mode


def category(name):
    value = name.lower()
    groups = [('Здания и части', ('house', 'hangar', 'building', 'office', 'slum', 'roof', 'shed', 'garage', 'door', 'market', 'tent')),
              ('Стены и ограждения', ('wall', 'fence', 'gate', 'barricade', 'corner')),
              ('Растительность', ('tree', 'bush', 'foliage', 'grass')),
              ('Грунт и дороги', ('ground', 'road', 'decal', 'pavement')),
              ('Интерьер', ('bed', 'chair', 'table', 'couch', 'indoor', 'shel', 'sink', 'toilet', 'stove', 'locker')),
              ('Предметы и укрытия', ('box', 'crate', 'barrel', 'tank', 'car', 'tire', 'junk', 'spool', 'tower', 'outpost'))]
    return next((label for label, words in groups if any(word in value for word in words)), 'Прочее')


CSS = '''body{margin:0;background:#10171d;color:#edf1f3;font:16px system-ui}header,main{max-width:1480px;margin:auto;padding:26px}a{color:#9ed4ec}h1{font-size:32px}p{max-width:1050px;line-height:1.6}.muted{color:#b0bec7;font-size:14px}nav{display:flex;gap:12px;flex-wrap:wrap}nav a,.tag{background:#263744;padding:7px 12px;border-radius:6px}input,select,button{padding:12px;background:#263744;color:white;border:1px solid #567080;border-radius:6px}input{min-width:280px}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(315px,1fr));gap:18px}article{background:#1b2730;border:1px solid #354651;border-radius:10px;padding:15px;overflow-wrap:anywhere}article h2{font-size:17px;margin:12px 0}article img{width:100%;height:245px;object-fit:contain;background:repeating-conic-gradient(#283640 0% 25%,#32424d 0% 50%) 50%/24px 24px;border-radius:6px}details img{height:150px}details a{display:block;margin:12px 0}code{font-size:12px}section{margin-top:24px}[hidden]{display:none!important}.controls{display:flex;gap:12px;flex-wrap:wrap;position:sticky;top:0;background:#10171df5;padding:14px 0;z-index:1}.count{color:#f0cb85}footer{padding:35px;color:#a6b8c5}'''
JS = '''const q=document.querySelector('#q'),cat=document.querySelector('#cat'),mode=document.querySelector('#mode');function filter(){let n=0;document.querySelectorAll('article[data-kind]').forEach(el=>{el.hidden=!(el.dataset.kind===mode.value&&(!cat.value||el.dataset.cat===cat.value)&&el.textContent.toLowerCase().includes(q.value.toLowerCase()));if(!el.hidden)n++});document.querySelector('#count').textContent=n+' карточек';}q.addEventListener('input',filter);cat.addEventListener('change',filter);mode.addEventListener('change',filter);filter();'''


def page(title, body, script=''):
    return '<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + html.escape(title) + '</title><style>' + CSS + '</style><body>' + body + '<footer>Оригинальные ресурсы установленного клиента TI Online · исследовательский каталог · 28.09.2026</footer><script>' + script + '</script></body></html>'


def main():
    (OUT / 'images').mkdir(parents=True, exist_ok=True)
    (OUT / 'thumbs').mkdir(exist_ok=True)
    textures, models, errors = [], [], []
    for path in sorted(BASE.rglob('*')):
        if path.suffix.lower() not in ('.png', '.tga', '.jpg', '.dds', '.bmp'):
            continue
        rel = path.relative_to(BASE).as_posix()
        raw = path.read_bytes()
        try:
            im, kind = decode(raw)
            ident = hashlib.sha256(rel.encode()).hexdigest()[:16]
            im.save(OUT / 'images' / (ident + '.png'))
            preview = im.crop(im.getchannel('A').getbbox() or (0, 0, *im.size))
            preview.thumbnail((700, 480))
            preview.save(OUT / 'thumbs' / (ident + '.png'))
            textures.append(dict(path=rel, family=rel.split('/')[0], name=path.name,
                                 category=category(rel), width=im.width, height=im.height,
                                 format=kind, sha256=hashlib.sha256(raw).hexdigest(),
                                 image=f'images/{ident}.png', thumb=f'thumbs/{ident}.png'))
        except Exception as error:
            errors.append(dict(path=rel, error=str(error)))
    by_name = {}
    for tex in textures:
        by_name.setdefault(tex['name'].lower(), []).append(tex)
    for path in sorted(BASE.rglob('*.t')):
        rel = path.relative_to(BASE).as_posix()
        raw = path.read_bytes().lower()
        refs = []
        for name, candidates in by_name.items():
            if name.encode('ascii') in raw:
                refs.extend(t['path'] for t in candidates)
        models.append(dict(path=rel, family=rel.split('/')[0] if '/' in rel else '_root',
                           name=path.name, category=category(rel), textures=sorted(set(refs))))
    index = {t['path']: t for t in textures}
    families = sorted({t['family'] for t in textures} | {m['family'] for m in models})
    assignments = json.loads((OUT / 'family-cities.json').read_text(encoding='utf-8'))
    def city_label(family):
        if family in assignments['assigned']:
            if family in assignments.get('shared_use',{}):
                return assignments['assigned'][family] + ' · также разрешён для ' + ', '.join(assignments['shared_use'][family]) + ' (28.09.2026)'
            return assignments['assigned'][family] + ' · распределение пользователя'
        if family in assignments['reservation_candidates']:
            return 'Кандидаты для Reservation · требуется сверка объектов; возможны общие ресурсы'
        return 'Специальные режимы / служебные ресурсы · вне обычного пула Reservation'
    nav = '<nav><a href="index.html">Все семейства</a>' + ''.join(f'<a href="{f}.html">{f}</a>' for f in families) + '</nav>'
    summary = []
    for family in families:
        ts = [t for t in textures if t['family'] == family]
        ms = [m for m in models if m['family'] == family]
        cards = []
        for m in ms:
            related = sorted([index[p] for p in m['textures']], key=lambda t: t['width'] * t['height'], reverse=True)
            preview_path = related[0]['thumb'] if related else ''
            if len(related) > 1:
                montage_name = hashlib.sha256('|'.join(t['path'] for t in related).encode()).hexdigest()[:16] + '-parts.png'
                preview_path = 'thumbs/' + montage_name
                if not (OUT / preview_path).exists():
                    montage = Image.new('RGBA', (700, 480))
                    for n, texture in enumerate(related[:4]):
                        part = Image.open(OUT / texture['thumb']); part.thumbnail((340, 230))
                        montage.alpha_composite(part, ((n % 2) * 350 + (350-part.width)//2, (n // 2)*240 + (240-part.height)//2))
                    montage.save(OUT / preview_path)
            picture = ('<a href="' + preview_path + '"><img loading="lazy" src="' + preview_path + '" alt="Исходные текстуры модели"></a>') if related else '<p class="muted">Ссылка на изображение не найдена. Нельзя подставлять картинку по сходству имени.</p>'
            details = ''.join('<a href="' + t['image'] + '"><img loading="lazy" src="' + t['thumb'] + '"><code>' + html.escape(t['path']) + '</code></a>' for t in related)
            cards.append(f'<article data-kind="model" data-cat="{m["category"]}">{picture}<h2>{html.escape(m["name"])}</h2><span class="tag">{m["category"]}</span><p><code>{html.escape(m["path"])}</code></p><p class="muted">Текстур: {len(related)}. Превью — исходная текстура/атлас, не собранная модель.</p><details><summary>Все текстуры модели</summary>{details}</details></article>')
        for t in ts:
            cards.append(f'<article data-kind="texture" data-cat="{t["category"]}"><a href="{t["image"]}"><img loading="lazy" src="{t["thumb"]}" alt="{html.escape(t["name"])}"></a><h2>{html.escape(t["name"])}</h2><p><code>{html.escape(t["path"])}</code></p><p>{t["width"]} × {t["height"]} · {t["category"]}</p><p class="muted">{t["format"]}</p></article>')
        cats = sorted({x['category'] for x in ts + ms})
        controls = '<div class="controls"><input id="q" placeholder="Поиск по имени ресурса"><select id="mode"><option value="model">Модели и объекты</option><option value="texture">Все текстуры</option></select><select id="cat"><option value="">Все категории</option>' + ''.join(f'<option>{c}</option>' for c in cats) + '</select><span id="count" class="count"></span></div>'
        body = f'<header>{nav}<h1>{family} — визуальный каталог</h1><p>{len(ms)} моделей · {len(ts)} изображений. Семейство определяется исходной папкой, а не названием города. Категории для поиска определены по именам файлов.</p><p class="muted">Ссылки текстур найдены по именам внутри .t. Части здания и атласы показаны отдельно; геометрия, двери и сборка модели здесь не воспроизводятся. Нажмите изображение для полного размера.</p></header><main>{controls}<section class="grid">' + ''.join(cards) + '</section></main>'
        body = body.replace(f'<h1>{family} — визуальный каталог</h1>', f'<h1>{family} — визуальный каталог</h1><p class="count">{city_label(family)}</p>')
        (OUT / f'{family}.html').write_text(page(f'TI Online / {family}', body, JS), encoding='utf-8')
        representative = max((t for t in ts if t['category'] == 'Здания и части'), key=lambda t:t['width']*t['height'], default=ts[0] if ts else None)
        summary.append(dict(family=family, city_classification=city_label(family), models=len(ms), textures=len(ts), linked=sum(bool(m['textures']) for m in ms), representative=representative))
    cards = ''.join(f'<article><a href="{s["family"]}.html">' + (f'<img src="{s["representative"]["thumb"]}">' if s['representative'] else '') + f'<h2>{s["family"]}</h2></a><p>{s["models"]} моделей · {s["textures"]} изображений</p><p class="muted">Моделей со ссылками на изображения: {s["linked"]}</p></article>' for s in summary)
    body = f'<header><p class="count">TI ONLINE / АРХИВ РЕСУРСОВ</p><h1>Здания, объекты и текстуры</h1><p>Отдельные каталоги исходных семейств клиента. {len(models)} моделей и {len(textures)} изображений. Это материалы для сравнения городов, а не утверждение о городской принадлежности каждого объекта.</p><p><a href="../reservation-maps/city-resource-classification.md">Основания классификации городов</a> · <a href="manifest.json">Полный машиночитаемый каталог</a></p><p class="muted">Карточки показывают оригинальные текстуры и атласы. Они не являются рендерами собранных зданий. Старые AJPG_EX декодированы с прозрачностью по алгоритму клиента. Исходные файлы не изменены.</p></header><main><section class="grid">{cards}</section></main>'
    for s in summary:
        body = body.replace(f'<h2>{s["family"]}</h2>', f'<h2>{s["family"]}</h2><p class="count">{s["city_classification"]}</p>')
    (OUT / 'index.html').write_text(page('TI Online — визуальные каталоги', body), encoding='utf-8')
    # Keep the explanatory link usable when serving just this directory.
    content = (OUT / 'index.html').read_text(encoding='utf-8').replace('../reservation-maps/city-resource-classification.md', 'city-resource-classification.md')
    (OUT / 'index.html').write_text(content, encoding='utf-8')
    (OUT / 'city-resource-classification.md').write_text((ROOT / 'reports/reservation-maps/city-resource-classification.md').read_text(encoding='utf-8'), encoding='utf-8')
    (OUT / 'manifest.json').write_text(json.dumps(dict(textures=textures, models=models, errors=errors, families=summary), ensure_ascii=False, indent=2), encoding='utf-8')
    font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 22)
    sheet = Image.new('RGB', (1400, 340 * ((len(summary) + 3) // 4)), '#10171d')
    draw = ImageDraw.Draw(sheet)
    for i, s in enumerate(summary):
        x, y = (i % 4) * 350, (i // 4) * 340
        if s['representative']:
            preview = Image.open(OUT / s['representative']['thumb']); preview.thumbnail((320, 260))
            sheet.paste(preview, (x + (350-preview.width)//2, y + (265-preview.height)//2), preview)
        draw.text((x+16, y+270), s['family'], font=font, fill='#9ed4ec')
        draw.text((x+16, y+301), f'{s["models"]} models / {s["textures"]} images', font=font, fill='white')
    sheet.save(OUT / 'overview.jpg', quality=92)
    print(json.dumps(dict(models=len(models), textures=len(textures), decoded=sum(t['format'].startswith('AJPG') for t in textures), linked=sum(bool(m['textures']) for m in models), errors=errors), ensure_ascii=False))


if __name__ == '__main__':
    main()
