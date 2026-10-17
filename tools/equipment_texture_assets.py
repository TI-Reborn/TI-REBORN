"""Inventory the exact hosted equipment resources; never use local player data."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import subprocess
import shlex
import urllib.request
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/equipment-textures'
ASSETS = ROOT / 'assets/equipment-textures-v1'
URL = 'https://185.184.42.88/updates/'
SSH = ['ssh', '-i', str(Path.home() / '.ssh/tio_server'), '-o', 'BatchMode=yes',
       '-o', 'ConnectTimeout=10', 'root@185.184.42.88']


def sha(data):
    return hashlib.sha256(data).hexdigest()


def remote(code):
    result = subprocess.run(SSH + ['python3 -c ' + shlex.quote(code)],
                            capture_output=True, text=True, encoding='utf-8')
    if result.returncode:
        raise RuntimeError(result.stderr)
    return json.loads(result.stdout)


def fetch(record):
    target = OUT / 'source' / record['path']
    if not target.exists():
        with urllib.request.urlopen(URL + 'blobs/' + record['sha256'], timeout=45) as response:
            data = response.read()
        assert len(data) == record['size'] and sha(data) == record['sha256'], record['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    assert target.stat().st_size == record['size'] and sha(target.read_bytes()) == record['sha256']
    return target


def prepare():
    import sys
    sys.path.insert(0, str(ROOT))
    from tools.build_visual_asset_catalog import decode
    OUT.mkdir(exist_ok=True)
    ASSETS.mkdir(exist_ok=True)
    inspection = remote("""import json,pathlib,sqlite3,subprocess,hashlib
d=sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)
p=pathlib.Path('/var/www/tio-client/updates/manifest.json');raw=p.read_bytes()
print(json.dumps(dict(service=subprocess.check_output(['systemctl','is-active','tio-server'],text=True).strip(),integrity=d.execute('PRAGMA integrity_check').fetchone()[0],accounts=d.execute('SELECT COUNT(*) FROM accounts').fetchone()[0],checkpoints=d.execute('SELECT COUNT(*) FROM battle_checkpoints').fetchone()[0],pending=d.execute('SELECT COUNT(*) FROM battle_settlement_jobs').fetchone()[0],client_manifest=raw.decode('utf-8'),manifest_sha256=hashlib.sha256(raw).hexdigest())))""")
    original = inspection.pop('client_manifest').encode('utf-8')
    (OUT / 'inspection.json').write_text(json.dumps(inspection, indent=2) + '\n')
    (OUT / 'previous-client-manifest.json').write_bytes(original)
    assert inspection['service'] == 'active' and inspection['integrity'] == 'ok'
    manifest = json.loads(original)
    records = {r['path']: r for r in manifest['files']}
    canonical = {p.lower(): p for p in records}
    items = ET.parse(fetch(records['base/shared config/items.xml'])).getroot()
    resources = {}
    bodies = {'chr_man_head.jpg', 'chr_woman_head.jpg', 'chr_man_body.jpg',
              'chr_woman_body.jpg', 'dog_alsatian.jpg',
              'dog_doberman.jpg', 'dog_huski.jpg', 'target_diffuse.jpg',
              'mob_sickminer.jpg', 'dog_infected.jpg'}
    models = set()
    coverage = []
    for item in items:
        fields = {n.get('key'): n.get('val') for n in item.findall('value')}
        image = fields.get('image')
        item_textures = set()
        for key, value in fields.items():
            if 'model_' in key:
                requested = 'base/models/' + value + '.mdjx'
                models.add(canonical.get(requested.lower(), requested))
            if 'texture_' in key and value not in bodies:
                path = 'base/models/' + value
                assert path in records, path
                resources.setdefault(path, dict(kind='atlas', names=set(), items=set()))
                resources[path]['names'].add(item.get('name', ''))
                resources[path]['items'].add(item.get('id'))
                item_textures.add(path)
        if image:
            path = 'base/items/' + image
            assert path in records, path
            resources.setdefault(path, dict(kind='icon', names=set(), items=set()))
            resources[path]['names'].add(item.get('name', ''))
            resources[path]['items'].add(item.get('id'))
        coverage.append(dict(id=item.get('id'), name=item.get('name'),
                             icon='base/items/' + image if image else None,
                             textures=sorted(item_textures),
                             original_models={k: v for k, v in fields.items() if 'model_' in k},
                             hidden_body=not image and any(v in bodies for k,v in fields.items() if 'texture_' in k)))
    # Camouflage color maps may be selected by the original material system.
    # Control masks are intentionally retained byte for byte.
    for path in list(resources):
        if resources[path]['kind'] != 'atlas':
            continue
        companion = str(Path(path).with_name(Path(path).stem + '_camo.jpg')).replace('\\', '/')
        if companion in records:
            resources[companion] = dict(kind='atlas', names=resources[path]['names'], items=resources[path]['items'])
    missing_models = sorted(models - records.keys())
    assert not missing_models, missing_models
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(fetch, (records[p] for p in sorted(resources))))
    inputs = ASSETS / 'inputs'
    inputs.mkdir(exist_ok=True)
    tasks = []
    for index, (path, resource) in enumerate(sorted(resources.items())):
        image, codec = decode(fetch(records[path]).read_bytes())
        identity = ('atlas-' if resource['kind'] == 'atlas' else 'icon-') + Path(path).stem.lower()
        dest = inputs / (identity + '.png')
        image.save(dest)
        transparent = image.getchannel('A').getextrema()[0] < 255
        names = ', '.join(sorted(resource['names']))
        if resource['kind'] == 'atlas':
            prompt = f'''Use case: precise-object-edit
Asset type: production diffuse UV texture atlas for the original Total Influence game equipment models; {Path(path).name}.
Input image 1 is the EDIT TARGET, the original complete flat UV atlas used in combat. It is NOT a picture of a assembled object. Equipment using it: {names}.
Primary request: repaint this exact UV atlas at high definition, retaining its original design and material colors but adding much better surface detail. Fine woven fabric, stitched seams and reinforced edging, layered armor plates, beveled plate edges, small rivets and screws, leather grain and grip ridges, brushed gunmetal, subtle scratches and controlled edge wear as appropriate to the existing regions. Keep equipment recognizable and readable at combat camera distance. For skin regions keep the original skin and anatomy intact, enhance only the existing worn equipment.
Composition: exact original canvas aspect ratio and complete atlas boundary; all UV islands, region boundaries, seams, bolts and component silhouettes in the same normalized pixel coordinates as the input. Add details INSIDE existing material regions. Fill the full canvas exactly as the original atlas, do not zoom or crop, do not rearrange or enlarge islands. High quality 1024px texture output with neutral diffuse lighting, no painted specular glare.
Constraints: preserve every original UV island position, orientation and outline, original palette, colors used for camouflage, original padding/background regions, original silhouette and any transparent cutouts. No geometry changes, no extra objects, no actual 3D object render, no labels, no text, no watermark, no frame. This texture must map correctly onto the untouched original male, female and companion meshes. Highest priority: exact spatial correspondence to the reference UV layout.'''
        else:
            prompt = f'''Use case: precise-object-edit
Asset type: game inventory equipment icon for Total Influence: {names}; original asset {Path(path).name}.
Input image 1 is the EDIT TARGET. Improve the rendering of this exact original icon with sharper, richer material detail and clean readable edges. Preserve the same item, design, count, silhouette, exact orientation, perspective, scale and position within the canvas, original proportions and original colors. Add fine seams, armor fasteners, brushed metal, leather or fabric grain, grip and machining detail, shell casings, crisp existing markings and controlled wear only where appropriate to the pictured item. Keep it readable when displayed small in the inventory. Render high quality.
Composition: keep the entire original canvas aspect ratio, object placement and padding. Do not enlarge, center, rotate, crop or redesign the object. Keep all separated components in their original positions.
Constraints: {'genuinely transparent background with the same object silhouette and cutouts' if transparent else 'preserve the original background exactly'}, no added item, no new text, no invented logos, no label, no watermark, no drop shadow outside the existing silhouette, no border. Preserve original colors to match its original model.''' 
        tasks.append(dict(id=identity, path=path, input=str(dest.resolve()), kind=resource['kind'],
                          source_size=list(image.size), native_codec=codec,
                          transparent=transparent, items=sorted(resource['items']),
                          names=names, prompt=prompt))
    assert len({t['id'] for t in tasks}) == len(tasks)
    (ASSETS / 'tasks.json').write_text(json.dumps(tasks, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (OUT / 'coverage.json').write_text(json.dumps(coverage, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    protected = {p: records[p] for p in records if p.endswith(('.mdjx','.rdl')) or '_mask' in p or p in ('base/shared config/items.xml','base/animation.xml','base/mobs.udf')}
    (OUT / 'protected-records.json').write_text(json.dumps(protected, indent=2) + '\n')
    print(json.dumps(dict(version=manifest['version'], items=len(items), tasks=len(tasks),
                          atlases=sum(t['kind']=='atlas' for t in tasks),
                          icons=sum(t['kind']=='icon' for t in tasks),
                          original_models=len(models), **inspection)))


if __name__ == '__main__':
    prepare()
