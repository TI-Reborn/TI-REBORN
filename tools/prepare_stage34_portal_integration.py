"""Copy frozen new portal files and emit two separately reviewed patch hunks."""
from datetime import datetime,timezone
import difflib
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/'reports/gameplay-followup/stage34-portal-integration'
SERVICES=ROOT/'reports/gameplay-followup/stage3-services-portal'
RATINGS=ROOT/'reports/gameplay-followup/stage4-ratings/portal/final'
WEB=ROOT/'web'


def sha(raw):return hashlib.sha256(raw).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    target=REPORT/'runtime/web'
    if target.exists():raise ValueError('Preserve previous portal integration work')
    pins=read(SERVICES/'source-pins.json');files={}
    for name,entry in pins['new_files'].items():
        raw=(SERVICES/'runtime/web'/name).read_bytes()
        if sha(raw)!=entry['candidate_sha256']:raise ValueError('Frozen services portal changed: '+name)
        files[name]=dict(raw=raw,source=str((SERVICES/'runtime/web'/name).relative_to(ROOT)),sha256=sha(raw))
    for name,pin in pins['imported_existing_helpers'].items():
        if sha((WEB/name).read_bytes())!=pin:raise ValueError('Services helper baseline changed: '+name)
    for name,entry in read(RATINGS/'web-manifest.json')['files'].items():
        raw=(RATINGS/entry['source']).read_bytes()
        if sha(raw)!=entry['sha256']:raise ValueError('Frozen ratings portal changed: '+name)
        files[name.removeprefix('web/')]=dict(raw=raw,source=str((RATINGS/entry['source']).relative_to(ROOT)),sha256=sha(raw))
    name='tests/ratings.test.ts';raw=(RATINGS/'web'/name).read_bytes()
    expected=read(RATINGS.parent/'validation2/web-validation.json')['source_sha256'][name]
    if sha(raw)!=expected:raise ValueError('Frozen ratings tests changed')
    files[name]=dict(raw=raw,source=str((RATINGS/'web'/name).relative_to(ROOT)),sha256=sha(raw))
    target.mkdir(parents=True)
    for name,entry in files.items():
        destination=target/name;destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(entry['raw'])
    changes={
        'src/lib/portal-routes.ts':("'assault', 'city', 'admin'", "'assault', 'city', 'services', 'ratings', 'admin'"),
        'src/components/content-pages.tsx':(
            "{user.role === 'ADMIN' && <Link className=\"text-link\"",
            "{user.status === 'ACTIVE' && user.gameUsername && <Link className=\"button button-outline\" href={`/${locale}/services`}>{locale === 'ru' ? 'Услуги и склады' : 'Services and warehouses'}</Link>}{user.status === 'ACTIVE' && user.gameUsername && <Link className=\"button button-outline\" href={`/${locale}/ratings`}>{locale === 'ru' ? 'Командные рейтинги' : 'Squad standings'}</Link>}{user.role === 'ADMIN' && <Link className=\"text-link\""),
    }
    hunks={};patch=''
    for name,(before,after) in changes.items():
        raw=(WEB/name).read_bytes();text=raw.decode('utf-8')
        if text.count(before)!=1:raise ValueError('Unexpected navigation baseline: '+name)
        amended=text.replace(before,after)
        hunks['web/'+name]=dict(before_sha256=sha(raw),after_sha256=sha(amended.encode('utf-8')),before=before,after=after,
                               justification='Add ACTIVE linked account services/ratings navigation; retain existing city and assault routes')
        patch+=''.join(difflib.unified_diff(text.splitlines(keepends=True),amended.splitlines(keepends=True),
                                          fromfile='a/web/'+name,tofile='b/web/'+name,n=2))
    (REPORT/'reviewed-hunks.json').write_text(json.dumps(dict(version=1,hunks=hunks,shared_web_modified=False),indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    (REPORT/'navigation.patch').write_text(patch,encoding='utf-8')
    source=dict(version=1,utc=datetime.now(timezone.utc).isoformat(),
                frozen_files={name:{k:v for k,v in entry.items() if k!='raw'} for name,entry in files.items()},
                services_manifest_sha256=sha((SERVICES/'source-pins.json').read_bytes()),
                ratings_manifest_sha256=sha((RATINGS/'web-manifest.json').read_bytes()),
                shared_web_modified=False,hosted_changes=False)
    (REPORT/'frozen-inputs.json').write_text(json.dumps(source,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(new_frozen_files=len(files),reviewed_hunks=len(hunks),shared_web_modified=False)))


if __name__=='__main__':main()
