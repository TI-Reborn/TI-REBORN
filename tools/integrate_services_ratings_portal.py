"""Apply only pinned new files and three reviewed portal edits."""
import hashlib,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DELIVERY=ROOT/'reports/gameplay-followup/stage34-portal-integration'
def sha(raw):return hashlib.sha256(raw).hexdigest()
def main():
    target=DELIVERY/'root-integration.json'
    if target.exists():raise ValueError('Preserve previous integration report')
    raw=(DELIVERY/'delivery-manifest.json').read_bytes()
    if sha(raw)!='02a33be40c3747f52ad36e4902622adcd3947c70ee913cfe85ee98376aec42c9':raise ValueError('Frozen portal manifest changed')
    manifest=json.loads(raw);hunks=json.loads((DELIVERY/'reviewed-hunks.json').read_text(encoding='utf-8'))['hunks'];changes={}
    for name,row in manifest['files'].items():
        path=ROOT/'web'/name;candidate=(DELIVERY/'runtime/web'/name).read_bytes()
        if sha(candidate)!=row['sha256']:raise ValueError('Frozen new source changed')
        existing=sha(path.read_bytes()) if path.is_file() else None
        if existing!=row['existingBaselineSha256']:raise ValueError('Portal baseline changed: '+name)
        if existing!=row['sha256']:changes[path]=candidate
    for name,row in hunks.items():
        path=ROOT/name;before=path.read_bytes()
        if sha(before)!=row['before_sha256']:raise ValueError('Reviewed portal target changed: '+name)
        value=before.decode('utf-8')
        for edit in row.get('edits',[row]):
            if value.count(edit['before'])!=1:raise ValueError('Reviewed portal edit boundary changed: '+name)
            value=value.replace(edit['before'],edit['after'])
        candidate=value.encode('utf-8')
        if sha(candidate)!=row['after_sha256']:raise ValueError('Reviewed portal result differs: '+name)
        changes[path]=candidate
    backup=DELIVERY/'root-previous-sources';pins={}
    for path,raw in changes.items():
        if path.exists():
            prior=backup/path.relative_to(ROOT);prior.parent.mkdir(parents=True,exist_ok=True);prior.write_bytes(path.read_bytes())
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw);pins[path.relative_to(ROOT).as_posix()]=sha(raw)
    target.write_text(json.dumps(dict(passed=True,reviewed_manifest_sha256=sha((DELIVERY/'delivery-manifest.json').read_bytes()),
        source_sha256=pins,unrelated_files_changed=False),indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=True,changed_files=len(changes),reviewed_existing_targets=3)))

if __name__=='__main__':main()
