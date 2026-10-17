"""Import legacy ability parameters without inventing missing levels or prices."""
import hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tio.abilities import AbilityCatalog


def main():
    source=Path(r'C:\Program Files (x86)\TIOnline\base\ability.cfg')
    catalog=AbilityCatalog.from_cfg(source)
    data={'source':str(source),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
          'status':'LEGACY_DEFINITIONS_PARTIAL_RUNTIME_SEE_WEAPON_EFFECTS_MD',
          'records':[{'id':r.ability_id,'level':r.level,'fields':r.fields} for r in catalog.records],
          'limitations':['Unspecified fields are unknown, not zero or inherited.',
                         'Names alone do not prove actor eligibility.',
                         'Learning prices, requirements and combat semantics are not inferred.']}
    (ROOT/'config/abilities.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'Imported {len(catalog.records)} records, {len(set(r.ability_id for r in catalog.records))-1} nonzero ability IDs.')


if __name__=='__main__':main()
