"""Build an asset-only release from the hosted manifest and verified AI exports."""
from pathlib import Path
import copy,json,sys,tarfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.equipment_texture_assets import ASSETS,OUT,sha
VERSION='2026.10.06.5'


def build():
    proof=json.loads((OUT/'asset-verification.json').read_text())
    assert proof['passed'] and proof['resources']==145
    previous=(OUT/'previous-client-manifest.json').read_bytes()
    old=json.loads(previous);new=copy.deepcopy(old)
    assert old['version']=='2026.10.06.4'
    new['version']=VERSION
    new['news']='Новые текстуры экипировки: детализированная броня и оружие в бою, обновлённые изображения предметов и боеприпасов.\n\n'+old['news']
    tasks=json.loads((ASSETS/'tasks.json').read_text(encoding='utf-8'))
    changes={t['path'] for t in tasks}
    release=OUT/'client-release';blobs=release/'blobs';blobs.mkdir(parents=True,exist_ok=True)
    for record in new['files']:
        if record['path'] in changes:
            assert not record.get('seed',False)
            raw=(OUT/'client'/record['path']).read_bytes()
            digest=sha(raw);(blobs/digest).write_bytes(raw)
            record.update(sha256=digest,size=len(raw))
    before={r['path']:r for r in old['files']};after={r['path']:r for r in new['files']}
    assert before.keys()==after.keys()
    assert {p for p in before if before[p]!=after[p]}==changes
    protected=json.loads((OUT/'protected-records.json').read_text())
    assert all(after[p]==record for p,record in protected.items())
    raw=(json.dumps(new,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    (release/'manifest.json').write_bytes(raw)
    (release/'previous-manifest.json').write_bytes(previous)
    (release/'allowed-paths.json').write_text(json.dumps(sorted(changes),indent=2)+'\n')
    with tarfile.open(OUT/'patch.tar.gz','w:gz') as tar:
        for file in sorted(release.rglob('*')):
            if file.is_file():tar.add(file,arcname=file.relative_to(release).as_posix())
    report=dict(version=VERSION,changed_files=len(changes),unchanged_files=len(before)-len(changes),
                original_geometry_files=len([p for p in protected if p.endswith('.mdjx')]),
                bytes=sum(after[p]['size'] for p in changes),manifest_sha256=sha(raw),
                previous_manifest_sha256=sha(previous),database_in_archive=False)
    (OUT/'release-verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))


if __name__=='__main__':build()
