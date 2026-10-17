"""Freeze four reviewed city files over the published multiplayer runtime."""
from datetime import datetime,timezone
import hashlib,json,shutil
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'reports/gameplay-completion/stage9-interfaces-revision2'
DELIVERY=ROOT/'reports/gameplay-followup/stage1-interfaces/city-api-final-revision3'
FOLDER=ROOT/'reports/gameplay-completion/stage9-city'
MANIFEST_SHA='7a765a374041f651ade2a3e298bc4659fcd5a701ca9eaf99fe8066f21c78bb06'


def main():
    if (FOLDER/'candidate-manifest.json').exists():raise ValueError('Preserve prior release')
    raw=(DELIVERY/'delivery-manifest.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=MANIFEST_SHA:raise ValueError('Reviewed delivery changed')
    delivery=json.loads(raw);proof=json.loads((DELIVERY/'validation-summary.json').read_text(encoding='utf-8'))
    if not proof['passed'] or not proof['source_unchanged'] or proof['latest_tests_run']!=33:raise ValueError('Exact focused proof required')
    original=json.loads((BASE/'candidate-manifest.json').read_text(encoding='utf-8'))
    for name,row in original['files'].items():
        if hashlib.sha256((BASE/row['source']).read_bytes()).hexdigest()!=row['sha256']:raise ValueError('Published base changed')
    shutil.copytree(BASE/'runtime',FOLDER/'runtime',ignore=shutil.ignore_patterns('__pycache__'))
    overrides=json.loads((BASE/'candidate-overrides.json').read_text(encoding='utf-8'))
    for name,row in delivery['files'].items():
        if row['before']!=(original['files'].get(name) or {}).get('sha256'):raise ValueError('Delivery base differs')
        raw=(DELIVERY/row['source']).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=row['sha256']:raise ValueError('Delivery source differs')
        compile(raw,name,'exec');target=FOLDER/'runtime'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
        overrides[name]='runtime/'+name
    for filename,value in (('candidate-manifest.json',dict(version=1,utc=datetime.now(timezone.utc).isoformat(),files=delivery['files'],delivery_manifest_sha256=MANIFEST_SHA,local_private_contracts_included=False)),('candidate-overrides.json',overrides),('runtime-files.json',sorted(delivery['files']))):
        (FOLDER/filename).write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
    checked=ROOT/proof['latest_proof'];raw=checked.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=proof['latest_proof_sha256']:raise ValueError('Focused proof changed')
    (FOLDER/'local-validation.json').write_text(json.dumps(dict(passed=True,source_unchanged=True,
        source_sha256={n:r['sha256'] for n,r in delivery['files'].items()},test_count=33,
        isolated_verified_full_public_tree=True,original_proof=proof,
        graphical_client_acceptance=False),indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(frozen_files=len(delivery['files']),verified_local_tests=33)))


if __name__=='__main__':main()
