"""Publish the exact one-byte password-cap change over the inspected live image."""
import base64, hashlib, json, sys, urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.publish_gameplay_equipment_client import PUBLISH
from tools.deploy_stage4_economy import remote
OUT = ROOT/'reports/password-recovery-20261023/client'

def main():
    assert json.loads((OUT/'native-loader64.json').read_text())['passed']
    assert json.loads((OUT/'native-field.json').read_text())['passed']
    assert (OUT/'launcher-password64.txt').read_text().startswith('PASS:')
    old = (OUT/'previous-manifest.json').read_bytes()
    manifest = json.loads(old)
    assert manifest['version'] == '2026.10.22.3'
    assert hashlib.sha256(old).hexdigest() == '48cfb92229b324476db5be4559cbc08572eb165ba0600a9c3536406904a17617'
    before = (OUT/'previous-silver.dll').read_bytes(); candidate = (OUT/'silver.dll').read_bytes()
    source_hash = hashlib.sha256(before).hexdigest(); digest = hashlib.sha256(candidate).hexdigest()
    assert source_hash == '717d89cd25912d593ac9b6cf0f593faac509f42d7572ccf63ba063f41cef9625'
    assert len(before) == len(candidate) == 8167936
    assert [i for i,(a,b) in enumerate(zip(before,candidate)) if a != b] == [0x47e1be]
    assert candidate[0x47e1b8:0x47e1bf] == bytes.fromhex('c6838002000040')
    row = next(r for r in manifest['files'] if r['path'] == 'silver.dll')
    assert row['sha256'] == source_hash
    row.update(sha256=digest, size=len(candidate)); manifest['version'] = '2026.10.23.1'
    new = (json.dumps(manifest, ensure_ascii=False, indent=2)+'\n').encode()
    plan = dict(previous_sha256=source_hash, updated_sha256=digest,
        all_other_published_bytes_preserved=True, appended_bytes=0,
        changes=[dict(offset=0x47e1be, before_hex='10', after_hex='40')])
    source = PUBLISH.replace("len(plan['changes'])!=7", "len(plan['changes'])!=1")
    source = source.replace("plan=p['plan']", "plan=p['plan']\nassert plan['changes']==[dict(offset=0x47e1be,before_hex='10',after_hex='40')]\nassert raw[0x47e1b8:0x47e1bf]==bytes.fromhex('c6838002000040')")
    source = source.replace('tio-before-equipment-client-', 'tio-before-password64-client-')
    # Archive publication uses its own lock in addition to the common manifest lock.
    source = source.replace("def sha(raw):", "archive_lock=open('/root/tio-client-archive-publication.lock','a');fcntl.flock(archive_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)\ndef sha(raw):")
    report = remote(source, dict(before_manifest=base64.b64encode(old).decode(),
        after_manifest=base64.b64encode(new).decode(), candidate=base64.b64encode(candidate).decode(),
        base_sha256=source_hash, plan=plan))
    (OUT/'client-publication.json').write_text(json.dumps(report, indent=2))
    (OUT/'manifest.json').write_bytes(new)
    origin = 'https://185.184.42.88/updates/'
    assert urllib.request.urlopen(origin+'manifest.json', timeout=30).read() == new
    assert hashlib.sha256(urllib.request.urlopen(origin+'blobs/'+digest, timeout=45).read()).hexdigest() == digest
    (OUT/'client-https.json').write_text(json.dumps(dict(passed=True, trusted_https=True,
        sha256=digest, version=manifest['version']), indent=2))
    print(json.dumps(report))

if __name__ == '__main__': main()
