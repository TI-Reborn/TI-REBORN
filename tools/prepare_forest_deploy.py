"""Guarded runtime/client overlay against this turn's actual hosted baseline."""
from forest_biomes_assets import *
import tarfile

def main():
    before=json.loads((OUT/'before-hashes.json').read_text())
    code="""import pathlib,hashlib,json,sys
r=pathlib.Path('/opt/tio-emulator');print(json.dumps({n:(hashlib.sha256((r/n).read_bytes()).hexdigest() if (r/n).exists() else None) for n in json.load(sys.stdin)}))"""
    p=subprocess.run(SSH+['python3 -c '+shlex.quote(code)],input=json.dumps(SERVER_FILES),capture_output=True,text=True)
    if p.returncode:raise RuntimeError(p.stderr)
    assert json.loads(p.stdout)==before,'Hosted sources changed since inspection'
    guard={n:dict(before=before[n],after=sha((ROOT/n).read_bytes())) for n in SERVER_FILES}
    (OUT/'manifest.json').write_text(json.dumps(guard,indent=2))
    previous=(OUT/'previous-client-manifest.json').read_bytes();client=json.loads(previous)
    records={r['path']:r for r in client['files']};release=OUT/'client-release';(release/'blobs').mkdir(parents=True,exist_ok=True)
    for f in (OUT/'client').rglob('*'):
        if not f.is_file():continue
        name=f.relative_to(OUT/'client').as_posix();raw=f.read_bytes();digest=sha(raw)
        (release/'blobs'/digest).write_bytes(raw)
        if name not in records:records[name]=dict(path=name);client['files'].append(records[name])
        records[name].update(size=len(raw),sha256=digest,seed=False)
    client['version']='2026.10.06.2'
    client['news']='Случайные встречи теперь проходят в трёх лесных биомах: выжженном, осеннем и влажном заражённом. Следующая встреча не повторяет предыдущий биом. Ящики со снаряжением убраны. После победы добыча с каждой собаки — одна шкура и две порции мяса — поступает в рюкзак; если он заполнен, на личный склад. Шкуры продаются магазину за 30 кредитов, мясо за 10, или через аукцион. Обновите клиент через лаунчер перед игрой.\n\n'+client['news']
    (release/'manifest.json').write_text(json.dumps(client,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (release/'previous-manifest.json').write_bytes(previous)
    with tarfile.open(OUT/'patch.tar.gz','w:gz') as tar:
        for n in SERVER_FILES:tar.add(ROOT/n,arcname=n)
        tar.add(OUT/'manifest.json',arcname='manifest.json')
        for p in release.rglob('*'):
            if p.is_file():tar.add(p,arcname='client/'+p.relative_to(release).as_posix())
    print(json.dumps(dict(server_files=len(guard),client_files=sum(p.is_file() for p in (OUT/'client').rglob('*')),version=client['version'])))

if __name__=='__main__':main()
