"""Back up the hosted database/code, then atomically publish immutable client assets."""
from contextlib import closing
from pathlib import Path
import hashlib,json,re,shutil,sqlite3,subprocess,tarfile,tempfile

ROOT=Path('/opt/tio-emulator')
DB=Path('/var/lib/tio-server/reservation.sqlite3')
LIVE=Path('/var/www/tio-client/updates')


def sha(raw):return hashlib.sha256(raw).hexdigest()
def active():return subprocess.check_output(['systemctl','is-active','tio-server'],text=True).strip()
def pid():return subprocess.check_output(['systemctl','show','tio-server','--property=MainPID','--value'],text=True).strip()
def hashes():return {p.relative_to(ROOT).as_posix():sha(p.read_bytes()) for folder in ('tio','server','config') for p in sorted((ROOT/folder).rglob('*')) if p.is_file() and '__pycache__' not in p.parts}


def main():
    stage=Path(tempfile.mkdtemp(prefix='tio-equipment-textures-stage-',dir='/root'))
    with tarfile.open('/root/tio-equipment-textures-patch.tar.gz') as tar:
        assert all(m.isfile() and (stage/m.name).resolve().is_relative_to(stage) for m in tar.getmembers())
        tar.extractall(stage,filter='data')
    old=(LIVE/'manifest.json').read_bytes();new=(stage/'manifest.json').read_bytes()
    assert old==(stage/'previous-manifest.json').read_bytes(),'Published baseline changed; refuse replacing a newer release'
    a=json.loads(old);b=json.loads(new)
    assert a['version']=='2026.10.06.4' and b['version']=='2026.10.06.5'
    before={r['path']:r for r in a['files']};after={r['path']:r for r in b['files']}
    allowed=set(json.loads((stage/'allowed-paths.json').read_text()))
    assert len(allowed)==145 and set(before)==set(after)
    assert {p for p in before if before[p]!=after[p]}==allowed
    assert sum(p.startswith('base/models/') for p in allowed)==30
    assert sum(p.startswith('base/items/') for p in allowed)==115
    assert all(Path(p).suffix.lower() in ('.jpg','.png','.tga') and '_mask' not in p for p in allowed)
    for path in allowed:
        record=after[path];assert re.fullmatch('[0-9a-f]{64}',record['sha256'])
        raw=(stage/'blobs'/record['sha256']).read_bytes()
        assert sha(raw)==record['sha256'] and len(raw)==record['size']
        assert not record.get('seed',False)
    assert active()=='active';original_code=hashes();original_pid=pid()
    backup=Path(tempfile.mkdtemp(prefix='tio-before-equipment-textures-',dir='/root'))
    with closing(sqlite3.connect(f'file:{DB}?mode=ro',uri=True)) as source,closing(sqlite3.connect(backup/'reservation.sqlite3')) as target:
        assert source.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        source.backup(target);assert target.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        accounts=target.execute('SELECT COUNT(*) FROM accounts').fetchone()[0]
    (backup/'reservation.sqlite3').chmod(0o600)
    for source,name in (('/etc/tio-server/server.toml','server.toml'),('/etc/systemd/system/tio-server.service','tio-server.service')):
        shutil.copy2(source,backup/name)
    with tarfile.open(backup/'previous-code-config.tar.gz','w:gz') as tar:
        for folder in ('tio','server','tools','config','evidence'):tar.add(ROOT/folder,arcname=folder)
    (backup/'client-manifest.json').write_bytes(old)
    (backup/'blobs').mkdir()
    for path in allowed:
        digest=before[path]['sha256'];source=LIVE/'blobs'/digest
        assert sha(source.read_bytes())==digest
        shutil.copy2(source,backup/'blobs'/digest)
    assert (LIVE/'manifest.json').read_bytes()==old and hashes()==original_code
    try:
        for path in allowed:
            digest=after[path]['sha256'];blob=LIVE/'blobs'/digest
            if blob.exists():assert sha(blob.read_bytes())==digest
            else:shutil.copy2(stage/'blobs'/digest,blob);blob.chmod(0o644)
        assert (LIVE/'manifest.json').read_bytes()==old
        temporary=LIVE/'manifest-equipment-textures.new'
        temporary.write_bytes(new);temporary.chmod(0o644);temporary.replace(LIVE/'manifest.json')
        assert active()=='active' and pid()==original_pid and hashes()==original_code
        with closing(sqlite3.connect(f'file:{DB}?mode=ro',uri=True)) as source:
            assert source.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            current_accounts=source.execute('SELECT COUNT(*) FROM accounts').fetchone()[0]
        assert current_accounts>=accounts
    except BaseException:
        temporary=LIVE/'manifest-equipment-textures-rollback.new'
        temporary.write_bytes(old);temporary.chmod(0o644);temporary.replace(LIVE/'manifest.json')
        raise
    report=dict(backup=str(backup),client_version=b['version'],changed_files=len(allowed),
                service='active',service_restarted=False,main_pid=original_pid,
                server_code_unchanged=True,accounts_in_backup=accounts,
                accounts_after=current_accounts,database_uploaded=False,
                integrity='ok',manifest_sha256=sha(new))
    (backup/'deployment.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))


if __name__=='__main__':main()
