"""Translate complete legacy value tables into the native skills.xml catalog.

Only parameters explicitly identical at every level become shared XML values.
No learning eligibility, prices, passive effects or missing ranks are invented.
"""
import hashlib,json,sys
from pathlib import Path
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tio.abilities import AbilityCatalog

MAPPING={'effect_text':'effectText','Range':'castRange','AP':'apConsume',
         'Cooldown':'reuseTurns','MinRange':'MinRange','SplashRange':'SplashRange',
         'hide':'hide','nocast':'nocast','soundnodelay':'soundnodelay'}
TARGETS={'self':'target_self','enemy':'target_one','area':'target_area'}

def build(catalog):
    root=ET.Element('skills');included=[];excluded=[]
    for ability_id in sorted({r.ability_id for r in catalog.records}-{0}):
        rows=sorted((r for r in catalog.records if r.ability_id==ability_id),key=lambda r:r.level or 0)
        maximum=rows[0].number('levels')
        if [r.level for r in rows]!=list(range(1,(maximum or 0)+1)) or any(r.number('value') is None for r in rows):
            excluded.append({'id':ability_id,'reason':'Incomplete explicit level/value table'});continue
        node=ET.SubElement(root,'skill',id=str(ability_id),name=rows[0].name)
        ET.SubElement(node,'table').text=' '.join(r.fields['value'] for r in rows)
        mapped={};unresolved={}
        for old,new in MAPPING.items():
            values=[r.fields.get(old) for r in rows]
            if values[0] is not None and len(set(values))==1:mapped[new]=values[0]
            elif any(v is not None for v in values):unresolved[old]=values
        active=[r.fields.get('Active',r.fields.get('active')) for r in rows]
        if all(v=='1' for v in active):mapped['operateType']='OP_ACTIVE'
        elif any(v=='1' for v in active):raise ValueError('Inconsistent active profile')
        target=[r.fields.get('Target') for r in rows]
        if target[0] is not None and len(set(target))==1:mapped['target']=TARGETS[target[0]]
        for key,val in mapped.items():ET.SubElement(node,'value',key=key,val=val)
        included.append({'id':ability_id,'levels':len(rows),'values':[r.number('value') for r in rows],
                         'mapped':mapped,'unresolved_per_level':unresolved})
    ET.indent(root)
    return ET.tostring(root,encoding='utf-8',xml_declaration=True),included,excluded

def main():
    source=Path(r'C:\Program Files (x86)\TIOnline\base\ability.cfg')
    from tio.miner_abilities import catalog_for_play,rules
    from tio.dog_abilities import catalog_for_play as dog_catalog
    xml,included,excluded=build(dog_catalog(catalog_for_play(AbilityCatalog.from_cfg(source))))
    (ROOT/'evidence/skills_diagnostic.xml').write_bytes(xml)
    report={'source':str(source),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
            'included':included,'excluded':excluded,'status':'MINER_AND_DOG_RULES_CONNECTED_OTHER_SKILLS_PARTIAL',
            'miner_overrides':rules(),
            'policy':'Unspecified or nonuniform parameters omitted; client defaults are not historical values. Do not use this catalog alone to enable combat or learning.'}
    from tio.dog_abilities import rules as dog_rules
    report['dog_overrides']=dog_rules()
    (ROOT/'evidence/skills_provenance.json').write_text(json.dumps(report,indent=2)+'\n')
    print(f'Built {len(included)} skills/{sum(r["levels"] for r in included)} levels; {len(excluded)} incomplete definitions excluded.')

if __name__=='__main__':main()
