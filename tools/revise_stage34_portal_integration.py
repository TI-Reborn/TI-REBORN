"""Add only the reviewed fund UI strings; retain the earlier integration proof."""
import difflib
import hashlib
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/'reports/gameplay-followup/stage34-portal-integration'
FUND=ROOT/'reports/gameplay-followup/stage4-defense-fund'
FROZEN=ROOT/'reports/gameplay-completion/stage11-warehouse-services-r6'
EDITS=[("text('Базы клана','Clan bases')","text('Базы и фонд обороны','Bases and defense fund')"),
       ("text('У вашего клана пока нет баз.','Your clan has no bases yet.')","text('Нет доступных баз или открытых фондов обороны.','No owned bases or open defense funds are available.')"),
       ("text('Внести из сейфа клана, Credits','Donate from clan safe, Credits')","text('Внести из личных кредитов, Credits','Donate from personal Credits')"),
       ('max={status.clan?.credits??0}','max={Math.min(status.balances?.credits??0,0xffffffff-event.fund)}')]


def sha(raw):return hashlib.sha256(raw).hexdigest()
def main():
    review=REPORT/'reviewed-hunks.json';value=json.loads(review.read_text(encoding='utf-8'))
    if 'web/src/components/city-operations.tsx' in value['hunks']:raise ValueError('Retain existing fund integration revision')
    source_pins=json.loads((FUND/'source-pins.json').read_text(encoding='utf-8'))['portal']
    diff=(FUND/'portal-diff/city-operations.tsx.diff').read_bytes()
    if sha(diff)!=source_pins['minimal_diff_sha256']:raise ValueError('Frozen fund portal diff changed')
    path=ROOT/'web/src/components/city-operations.tsx';raw=path.read_bytes()
    if sha(raw)!=source_pins['source_sha256']:raise ValueError('Fund UI exact baseline changed')
    text=raw.decode('utf-8');after=text
    for before,next in EDITS:
        if after.count(before)!=1:raise ValueError('Ambiguous fund UI replacement')
        if before not in diff.decode('utf-8') or next not in diff.decode('utf-8'):raise ValueError('Unexpected frozen fund UI replacement')
        after=after.replace(before,next)
    minus=[line[1:] for line in diff.decode('utf-8').splitlines() if line.startswith('-') and not line.startswith('---')]
    plus=[line[1:] for line in diff.decode('utf-8').splitlines() if line.startswith('+') and not line.startswith('+++')]
    if len(minus)!=1 or len(plus)!=1 or after.splitlines()[text.splitlines().index(minus[0])]!=plus[0]:
        raise ValueError('Four fund edits do not reproduce the reviewed diff')
    retained=REPORT/'revisions/stage11-r5';retained.mkdir(parents=True)
    shutil.copyfile(review,retained/'reviewed-hunks.json')
    shutil.copyfile(REPORT/'navigation.patch',retained/'navigation.patch')
    old_fixture=REPORT/'runtime/web/tests/fixtures/stage11-services.json'
    # Both checked absolute targets are inside this owned report directory.
    old_destination=retained/'stage11-services.json'
    if not old_fixture.resolve().is_relative_to(REPORT.resolve()) or not old_destination.resolve().is_relative_to(REPORT.resolve()):raise ValueError('Unconfined report move')
    old_fixture.rename(old_destination)
    value['hunks']['web/src/components/city-operations.tsx']=dict(before_sha256=sha(raw),after_sha256=sha(after.encode()),
        edits=[dict(before=before,after=next) for before,next in EDITS],
        justification='Accepted personal defender fund payer and escrow headroom; CityV1 DTO unchanged',
        frozenDiff='reports/gameplay-followup/stage4-defense-fund/portal-diff/city-operations.tsx.diff',frozenDiffSha256=sha(diff))
    review.write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    patch=(retained/'navigation.patch').read_text(encoding='utf-8')+''.join(difflib.unified_diff(text.splitlines(keepends=True),after.splitlines(keepends=True),
        fromfile='a/web/src/components/city-operations.tsx',tofile='b/web/src/components/city-operations.tsx',n=2))
    (REPORT/'navigation.patch').write_text(patch,encoding='utf-8')
    frozen_validation=json.loads((FUND/'portal-validation.json').read_text(encoding='utf-8'))
    test=(FUND/'tests/base-fund.test.ts').read_bytes()
    if sha(test)!=frozen_validation['test_sha256']:raise ValueError('Frozen fund UI tests changed')
    (REPORT/'runtime/web/tests/base-fund.test.ts').write_bytes(test)
    catalogue=FROZEN/'runtime/evidence/items_diagnostic.xml'
    names=[item.get('name',str(item.get('id'))) for item in ET.parse(catalogue).getroot()]
    maximum=max(map(len,names));longest=sorted(names,key=len,reverse=True)[:3]
    (REPORT/'mark-name-audit.json').write_text(json.dumps(dict(catalogue=str(catalogue.relative_to(ROOT)),sha256=sha(catalogue.read_bytes()),
        names=len(names),maximumCharacters=maximum,longest=longest,existingPortalLimit=64,expanded=False,allCurrentNamesFit=maximum<=64),indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(reviewedFiles=3,fundEdits=4,maximumItemName=maximum,sharedWebModified=False)))


if __name__=='__main__':main()
