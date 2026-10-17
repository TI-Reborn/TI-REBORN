"""Build a local gallery from unedited screenshots of hosted graphical battles."""
import hashlib
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT/'reports/arena-surroundings-implementation/screenshots'
SIDES = ('north_west', 'north_east', 'south_west', 'south_east')
LABELS = dict(north_west='Северо-запад', north_east='Северо-восток',
              south_west='Юго-запад', south_east='Юго-восток')
CITIES = dict(reservation='Reservation', denver='Denver', new_york='New York',
              military_zone='Military Zone')


def main():
    data = json.loads((FOLDER/'captures.json').read_text('utf-8'))
    records = data['captures']
    sections = []
    for city, title in CITIES.items():
        photos = [r for r in records if r['city'] == city]
        assert {r['side'] for r in photos} == set(SIDES) and len(photos) == 4
        assert len({r['match'] for r in photos}) == 1
        assert len({r['scene'] for r in photos}) == 1
        cards = []
        for side in SIDES:
            record = next(r for r in photos if r['side'] == side)
            path = (FOLDER/record['file']).resolve()
            assert path.is_relative_to(FOLDER.resolve()) and path.suffix.lower() in ('.png', '.jpg', '.jpeg')
            assert hashlib.sha256(path.read_bytes()).hexdigest() == record['sha256']
            assert record['source'] == 'sky.get_window_state'
            source = html.escape(record['file'], quote=True)
            cards.append(f'<figure><a href="{source}" target="_blank"><img src="{source}" '
                         f'alt="{title}: {LABELS[side]}"></a><figcaption>{LABELS[side]}</figcaption></figure>')
        variant = html.escape(photos[0]['variant'])
        sections.append(f'<section><h2>{title} · {variant}</h2><div class="grid">'+''.join(cards)+'</div></section>')
    content = '''<!doctype html><html lang="ru"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Окружение арены — снимки из боя</title>
<style>body{margin:0;padding:24px;background:#171b16;color:#e5e6db;font:16px system-ui}
main{max-width:1700px;margin:auto}h1{font-size:27px}h2{font-size:22px;margin:32px 0 12px}
p{color:#b8bfad}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}
figure{margin:0;background:#252c21;border:1px solid #444c37;border-radius:8px;overflow:hidden}
img{display:block;width:100%;height:auto}figcaption{padding:10px 14px}
a{color:#c2d391}@media(max-width:800px){.grid{grid-template-columns:1fr}body{padding:12px}}</style>
<main><h1>Окружение арены со всех четырёх сторон</h1>
<p>Снимки настоящих боёв на хостинге. Два отдельных игровых клиента подключены к общему бою.
Откройте изображение, чтобы увидеть его в исходном размере.</p>'''+''.join(sections)+'</main></html>'
    (FOLDER/'review.html').write_text(content, 'utf-8')
    print(json.dumps(dict(passed=True, cities=4, native_battle_screenshots=len(records),
                          output=str(FOLDER/'review.html'))))


if __name__ == '__main__':
    main()
