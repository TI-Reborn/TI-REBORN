"""Read-only image checks and archive packaging for the generated weapon art."""
import hashlib
import json
import zipfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'assets/weapon-icons-v1'
SIZES = [(64, 32), (128, 64), (256, 128), (512, 256), (128, 128), (256, 256)]


def main():
    catalog = json.loads((ASSETS / 'catalog.json').read_text(encoding='utf-8'))
    hosted = json.loads((ASSETS / 'hosted-weapon-catalog.json').read_text(encoding='utf-8'))
    package = json.loads((ASSETS / 'package.json').read_text(encoding='utf-8'))
    generation = json.loads((ASSETS / 'generation.json').read_text(encoding='utf-8'))
    items = catalog['items']
    assert len(items) == 45 and len({i['id'] for i in items}) == 45
    assert {str(i['id']) for i in items} == set(hosted['weapons'])
    assert package['complete'] and package['generated_icons'] == 45
    assert isinstance(package['installed'], bool) and generation['tool'] == 'built-in image_gen'
    records = {r['id']: r for r in generation['files']}
    assert len(records) == 45
    sources = []
    exports = []
    for item in items:
        assert item['name'] == hosted['weapons'][str(item['id'])]['name']
        record = records[item['id']]
        source = ASSETS / item['file']
        raw = source.read_bytes()
        assert raw == Path(record['source']).read_bytes()
        assert record['prompt'] == item['prompt']
        with Image.open(source) as image:
            assert image.mode == 'RGBA'
            assert image.getchannel('A').getextrema()[0] == 0
        sources.append(dict(id=item['id'], name=item['name'], file=item['file'], sha256=hashlib.sha256(raw).hexdigest()))
        for size in SIZES:
            path = ASSETS / 'exports' / f'{size[0]}x{size[1]}' / item['file']
            with Image.open(path) as image:
                assert image.size == size and image.mode == 'RGBA'
                assert image.getchannel('A').getextrema()[0] == 0
                assert image.getchannel('A').getbbox(), path
            exports.append(dict(path=path.relative_to(ASSETS).as_posix(), sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    for n in range(1, 4):
        with Image.open(ASSETS / f'preview-{n:02}.png') as image:
            assert image.size == (1500, 1140)
    report = dict(passed=True, generated_icons=45, exports=270,
                  original_hosted_names_preserved=True, source_bytes_preserved=True,
                  alpha_preserved=True, installed=package['installed'], sources=sources, export_files=exports)
    (ASSETS / 'validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    archive = ROOT / 'output/weapon-icons-v1.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as handle:
        for path in sorted(ASSETS.rglob('*')):
            if path.is_file():
                handle.write(path, path.relative_to(ASSETS.parent))
    with zipfile.ZipFile(archive) as handle:
        assert handle.testzip() is None
        assert sum(n.startswith('weapon-icons-v1/exports/') and n.endswith('.png') for n in handle.namelist()) == 270
    print(json.dumps(dict(passed=True, icons=45, exports=270, archive=str(archive), bytes=archive.stat().st_size)))


if __name__ == '__main__':
    main()
