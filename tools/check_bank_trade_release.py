"""Build and check both prepared patches against a fresh production snapshot."""
from pathlib import Path
import hashlib, io, json, shutil, subprocess, sys, tarfile, unittest

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'work/bank-trade-release-20261015'
REPORT=ROOT/'reports/bank-trade-release-20261015'
SSH=['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes',
     '-o','ConnectTimeout=8','root@185.184.42.88']

def main():
    REPORT.mkdir(parents=True,exist_ok=True)
    WORK.mkdir(parents=True,exist_ok=True)
    remote_source=WORK/'remote-source'; candidate=WORK/'candidate'
    if not (remote_source/'evidence/items_diagnostic.xml').is_file():
        code="""from pathlib import Path
import io,sys,tarfile
root=Path('/opt/tio-emulator')
with tarfile.open(fileobj=sys.stdout.buffer,mode='w|gz') as archive:
 for directory in ('server','tio','tools','config','evidence'):
  for path in sorted((root/directory).rglob('*')):
   if path.is_file() and '__pycache__' not in path.parts and path.suffix in ('.py','.json','.toml','.xml'):
    archive.add(path,arcname=str(path.relative_to(root)),recursive=False)
"""
        result=subprocess.run(SSH+['/opt/tio-emulator/.venv/bin/python -'],input=code.encode(),capture_output=True,timeout=60)
        if result.returncode:raise RuntimeError('Source capture failed')
        (REPORT/'runtime-before.tar.gz').write_bytes(result.stdout)
        with tarfile.open(fileobj=io.BytesIO(result.stdout)) as archive:
            archive.extractall(remote_source,filter='data')
    baseline={p.relative_to(remote_source).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
              for p in remote_source.rglob('*') if p.is_file()}
    (REPORT/'runtime-before-sha256.json').write_text(json.dumps(baseline,indent=2))
    if not candidate.exists():shutil.copytree(remote_source,candidate)
    for source in (remote_source/'evidence').glob('*.xml'):
        shutil.copy2(source,candidate/'evidence'/source.name)
    sources=json.loads((ROOT/'reports/trade-operations-20261015/source-map.json').read_text())
    sources.update({p:str(ROOT/p) for p in ('server/bank_operations.py','server/bank_gameplay.py','server/city_operations.py')})
    sealed={}
    for stage in ('bank','trade'):
        sealed.update(json.loads((ROOT/f'reports/{stage}-operations-20261015/patch-manifest.json').read_text()))
    manifest={}
    for name,source in sources.items():
        raw=Path(source).read_bytes(); after=hashlib.sha256(raw).hexdigest()
        assert after==sealed[name]['after'],name+' differs from checked patch'
        assert baseline.get(name)==sealed[name]['before'],name+' production source changed'
        manifest[name]=dict(before=baseline.get(name),after=after)
        (candidate/name).write_bytes(raw)
    (REPORT/'patch-manifest.json').write_text(json.dumps(manifest,indent=2))
    (REPORT/'source-map.json').write_text(json.dumps(sources,indent=2))
    with tarfile.open(REPORT/'bank-trade-release.tar.gz','w:gz') as archive:
        archive.add(REPORT/'patch-manifest.json',arcname='manifest.json')
        for name in sorted(manifest):archive.add(candidate/name,arcname=name)
    sys.path[:0]=[str(candidate),str(ROOT/'tests'),str(ROOT),str(ROOT/'work/bank-operations-20261015/test-dependencies')]
    import tools
    tools.__path__=[str(candidate/'tools'),str(ROOT/'tools')]
    import tools.loopback_exchange
    assert Path(tools.loopback_exchange.__file__).resolve()==(candidate/'tools/loopback_exchange.py').resolve()
    suites=['test_game_operations','test_service_operations','test_city_services','test_services',
        'test_city_services_integration','test_bank_gameplay','test_city_operations','test_bank_operations',
        'test_player_trade','test_player_trade_transport','test_player_auction','test_private_market',
        'test_private_market_refresh','test_trade_window_refresh','test_sc_auction',
        'test_sc_auction_view.SCViewTests','test_market_operations']
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromNames(suites))
    report=dict(passed=result.wasSuccessful(),tests=result.testsRun,failures=len(result.failures),
        errors=len(result.errors),skipped=len(result.skipped),suites=suites,files=len(manifest),
        archive_sha256=hashlib.sha256((REPORT/'bank-trade-release.tar.gz').read_bytes()).hexdigest())
    (REPORT/'automated-checks.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report));sys.exit(not result.wasSuccessful())

if __name__=='__main__':main()
