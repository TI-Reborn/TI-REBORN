"""Apply bounded edits to the freshly inspected hosting sources."""
import hashlib,json,sys,urllib.request
from pathlib import Path
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
WORK=ROOT/'work/awp-scope-20261019';OUT=ROOT/'reports/awp-scope-20261019'
FILES=('tio/sniper_scope.py','tio/combat.py','tio/arena_service.py','tio/weapon_effects.py',
       'tools/build_skills_fixture.py','evidence/skills_diagnostic.xml')
sha=lambda raw:hashlib.sha256(raw).hexdigest()

def main():
    replacements={
        'tio/combat.py':[("any(e.ability_id==27 for e","any(e.ability_id in (9,27) for e")],
        'tio/arena_service.py':[("not in (12,22,26,27)","not in (9,12,22,26,27)"),
            ("        if request.ability_id==12:","        if request.ability_id==9:\n            from .sniper_scope import cast\n            replies=cast(field.combat,character_id,request,view=view)\n        elif request.ability_id==12:")],
    }
    from tio.abilities import AbilityCatalog
    from tools.build_skills_fixture import build
    xml,_,_=build(AbilityCatalog.from_cfg(Path(r'C:\Program Files (x86)\TIOnline\base\ability.cfg')))
    node=ET.fromstring(xml).find("skill[@id='9']")
    snippet=ET.tostring(node,encoding='unicode').strip()
    def insert(raw):
        assert b'<skill id="9"' not in raw
        anchor=b'  <skill id="10"';assert raw.count(anchor)==1
        return raw.replace(anchor,('  '+snippet+'\n  <skill id="10"').encode())
    for name in FILES:
        p=WORK/'candidate'/name;p.parent.mkdir(parents=True,exist_ok=True)
        if name in replacements:
            source=(WORK/'baseline'/name).read_text(encoding='utf-8')
            for old,new in replacements[name]:
                assert source.count(old)==1,(name,old);source=source.replace(old,new)
            raw=source.encode()
        elif name.endswith('.xml'):raw=insert((WORK/'baseline'/name).read_bytes())
        else:raw=(ROOT/name).read_bytes()
        p.write_bytes(raw)
        if name.endswith('.py'):compile(raw,name,'exec')
    local=ROOT/'evidence/skills_diagnostic.xml'
    if b'<skill id="9"' not in local.read_bytes():local.write_bytes(insert(local.read_bytes()))
    origin='https://185.184.42.88/updates/'
    manifest=urllib.request.urlopen(origin+'manifest.json',timeout=30).read()
    (WORK/'manifest-before.json').write_bytes(manifest)
    row=next(r for r in json.loads(manifest)['files'] if r['path']=='base/shared config/skills.xml')
    raw=urllib.request.urlopen(origin+'blobs/'+row['sha256'],timeout=30).read()
    assert sha(raw)==row['sha256']
    (WORK/'client-skills-before.xml').write_bytes(raw)
    (WORK/'client-skills-candidate.xml').write_bytes(insert(raw))
    review={n:dict(before=sha((WORK/'baseline'/n).read_bytes()) if (WORK/'baseline'/n).exists() else None,
                   after=sha((WORK/'candidate'/n).read_bytes())) for n in FILES}
    (OUT/'server-review.json').write_text(json.dumps(review,indent=2))
    print(json.dumps(review))

if __name__=='__main__':main()
