"""Prepare guarded server and client overlays against the actual published state."""
from pathlib import Path
import hashlib,json,shlex,subprocess,tarfile
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'reports/dog-encounters'
SSH=['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','-o','ConnectTimeout=10','root@185.184.42.88']
FILES=('tio/world_encounters.py','tio/locations.py','tio/arena_service.py','tio/battle_rewards.py','tio/weapons.py','tio/combat.py',
       'tio/ranks.py','server/runtime.py','server/battle_reconnect.py','tools/encounter_scene.py','tools/loopback_exchange.py',
       'config/world_encounters.json','config/weapon_catalog.json','evidence/items_diagnostic.xml')

def main():
    script="""import pathlib,json,sys,hashlib
r=pathlib.Path('/opt/tio-emulator');print(json.dumps({n:hashlib.sha256((r/n).read_bytes()).hexdigest() if (r/n).exists() else None for n in json.load(sys.stdin)}))"""
    result=subprocess.run(SSH+['python3 -c '+shlex.quote(script)],input=json.dumps(FILES),capture_output=True,text=True,encoding='utf-8')
    if result.returncode:raise RuntimeError(result.stderr)
    before=json.loads(result.stdout)
    initial=json.loads((OUT/'before-hashes.json').read_text())
    for name,digest in before.items():
        if name in initial:assert digest==initial[name],f'Hosted source changed since inspection: {name}'
    manifest={name:dict(before=before[name],after=hashlib.sha256((ROOT/name).read_bytes()).hexdigest()) for name in FILES}
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    previous=(OUT/'previous-client-manifest.json').read_bytes();client=json.loads(previous)
    records={r['path']:r for r in client['files']}
    new=OUT/'client-release';(new/'blobs').mkdir(parents=True,exist_ok=True)
    for relative,name in [('base/mobs.udf','mobs.udf'),('base/animation.xml','animation.xml'),
                          ('base/shared config/items.xml','items.xml'),('base/models/dog_infected.jpg','dog_infected.jpg')]:
        raw=(OUT/'client'/name).read_bytes();digest=hashlib.sha256(raw).hexdigest()
        (new/'blobs'/digest).write_bytes(raw)
        if relative in records:record=records[relative]
        else:record=dict(path=relative);client['files'].append(record)
        record.update(size=len(raw),sha256=digest,seed=False)
    client['version']='2026.10.06.1'
    client['news']='На глобальной карте появились случайные встречи с заражёнными собаками. Нападения происходят во время пути вне городов. Победа приносит кредиты и боевой опыт; после боя отряд возвращается на карту в точку встречи. Обновление клиента обязательно для нового вида собак.\n\n'+client['news']
    (new/'manifest.json').write_text(json.dumps(client,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (new/'previous-manifest.json').write_bytes(previous)
    with tarfile.open(OUT/'patch.tar.gz','w:gz') as tar:
        for name in FILES:tar.add(ROOT/name,arcname=name)
        tar.add(OUT/'manifest.json',arcname='manifest.json')
        for file in new.rglob('*'):
            if file.is_file():tar.add(file,arcname='client/'+file.relative_to(new).as_posix())
    print(json.dumps(dict(server_files=len(FILES),client_version=client['version'],changed_client_files=4)))

if __name__=='__main__':main()
