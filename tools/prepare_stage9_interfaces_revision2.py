"""Retain revision1 evidence; add a scoped passive market-window fix."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]
PREVIOUS=ROOT/'reports/gameplay-completion/stage9-interfaces'
FOLDER=ROOT/'reports/gameplay-completion/stage9-interfaces-revision2'
BASE=ROOT/'reports/gameplay-followup/stage1-interfaces/public-regression'


def main():
    if (FOLDER/'candidate-manifest.json').exists():raise ValueError('Preserve the frozen revision')
    old=json.loads((PREVIOUS/'candidate-manifest.json').read_text(encoding='utf-8'))
    for name,row in old['files'].items():
        if hashlib.sha256((PREVIOUS/row['source']).read_bytes()).hexdigest()!=row['sha256']:
            raise ValueError('Frozen revision1 changed: '+name)
    shutil.copytree(PREVIOUS/'runtime',FOLDER/'runtime')
    metadata=BASE/'snapshot.json'
    baseline=json.loads(metadata.read_text(encoding='utf-8'))['source_sha256']
    name='server/private_market.py';raw=(BASE/'snapshot'/name).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=baseline[name]:raise ValueError('Pinned public market source changed')
    before=b"        return (*self.balances(),self.listing(),*((self.sc_catalogue(),) if self.sc_open else ()))"
    after=b"        # Both native AE and F8 catalogue receivers show their windows.\n        # Local Close sends no request; passive polls must refresh assets only.\n        # Explicit AE queries and BD18 refresh still return current catalogues.\n        return self.balances()"
    if raw.count(before)!=1:raise ValueError('Public passive refresh boundary changed')
    candidate=raw.replace(before,after);compile(candidate,name,'exec')
    (FOLDER/'runtime'/name).write_bytes(candidate)
    files=dict(old['files']);files[name]=dict(source='runtime/'+name,before=baseline[name],sha256=hashlib.sha256(candidate).hexdigest())
    overrides=json.loads((PREVIOUS/'candidate-overrides.json').read_text(encoding='utf-8'))
    overrides[name]='runtime/'+name
    for filename,value in (
        ('candidate-manifest.json',dict(version=2,utc=datetime.now(timezone.utc).isoformat(),files=files,
            previous_manifest_sha256=hashlib.sha256((PREVIOUS/'candidate-manifest.json').read_bytes()).hexdigest(),
            public_baseline_sha256=hashlib.sha256(metadata.read_bytes()).hexdigest(),local_private_contracts_included=False)),
        ('runtime-files.json',sorted(files)),('candidate-overrides.json',overrides)):
        (FOLDER/filename).write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(frozen_files=len(files),scoped_market_edits=1,local_private_market_file_uploaded=False)))


if __name__=='__main__':main()
