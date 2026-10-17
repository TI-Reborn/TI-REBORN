"""Back up the live host and publish a two-texture release without restarting it."""
from pathlib import Path
from contextlib import closing
import hashlib,json,re,shutil,sqlite3,struct,subprocess,tarfile,tempfile
ROOT=Path('/opt/tio-emulator');DB=Path('/var/lib/tio-server/reservation.sqlite3');LIVE=Path('/var/www/tio-client/updates')
TARGETS={'base/setting/reservation_v2/rveel_box_01b.png','base/setting/reservation_v2/rvound_ny_detail_32.png'}
def sha(data):return hashlib.sha256(data).hexdigest()
def active():return subprocess.check_output(['systemctl','is-active','tio-server'],text=True).strip()
def code_hashes():return {n:sha((ROOT/n).read_bytes()) for n in ('tio/map_generation.py','config/reservation_visuals.json')}

def main():
    stage=Path(tempfile.mkdtemp(prefix='tio-crate-alpha-stage-',dir='/root'))
    with tarfile.open('/root/tio-crate-alpha-patch.tar.gz') as tar:
        assert all(m.isfile() and (stage/m.name).resolve().is_relative_to(stage) for m in tar.getmembers())
        tar.extractall(stage,filter='data')
    old=(LIVE/'manifest.json').read_bytes();new=(stage/'manifest.json').read_bytes()
    assert old==(stage/'previous-manifest.json').read_bytes(),'Published client baseline changed'
    a=json.loads(old);b=json.loads(new);assert a['version']=='2026.10.06.3' and b['version']=='2026.10.06.4'
    before={r['path']:r for r in a['files']};after={r['path']:r for r in b['files']}
    assert set(before)==set(after) and {n for n in before if before[n]!=after[n]}==TARGETS
    for name in TARGETS:
        record=after[name];assert re.fullmatch('[0-9a-f]{64}',record['sha256'])
        raw=(stage/'blobs'/record['sha256']).read_bytes()
        assert sha(raw)==record['sha256'] and len(raw)==record['size']
        assert raw[:2]==b'BM' and struct.unpack_from('<H',raw,28)[0]==32
    assert active()=='active';original_code=code_hashes()
    backup=Path(tempfile.mkdtemp(prefix='tio-before-crate-alpha-',dir='/root'))
    with closing(sqlite3.connect(f'file:{DB}?mode=ro',uri=True)) as source,closing(sqlite3.connect(backup/'reservation.sqlite3')) as target:
        assert source.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        source.backup(target);assert target.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        accounts=target.execute('SELECT COUNT(*) FROM accounts').fetchone()[0]
    for source,name in (('/etc/tio-server/server.toml','server.toml'),('/etc/systemd/system/tio-server.service','tio-server.service')):
        shutil.copy2(source,backup/name)
    with tarfile.open(backup/'previous-code-config.tar.gz','w:gz') as tar:
        for folder in ('tio','server','tools','config','evidence'):tar.add(ROOT/folder,arcname=folder)
    (backup/'client-manifest.json').write_bytes(old)
    (backup/'blobs').mkdir()
    for name in TARGETS:
        digest=before[name]['sha256'];shutil.copy2(LIVE/'blobs'/digest,backup/'blobs'/digest)
    assert (LIVE/'manifest.json').read_bytes()==old and code_hashes()==original_code
    try:
        for name in TARGETS:
            digest=after[name]['sha256'];blob=LIVE/'blobs'/digest
            if blob.exists():assert sha(blob.read_bytes())==digest
            else:shutil.copy2(stage/'blobs'/digest,blob);blob.chmod(0o644)
        temporary=LIVE/'manifest-crate-alpha.new';temporary.write_bytes(new);temporary.chmod(0o644);temporary.replace(LIVE/'manifest.json')
        assert active()=='active' and code_hashes()==original_code
    except BaseException:
        temporary=LIVE/'manifest-crate-alpha-rollback.new';temporary.write_bytes(old);temporary.chmod(0o644);temporary.replace(LIVE/'manifest.json')
        raise
    report=dict(backup=str(backup),client_version=b['version'],changed_files=sorted(TARGETS),service='active',
                service_restarted=False,server_code_unchanged=original_code,accounts_in_backup=accounts,
                database_uploaded=False,manifest_sha=sha(new))
    (backup/'deployment.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))

if __name__=='__main__':main()
