"""Read-only inventory of installed ground.xml brush dependencies.

Presence is not proof of loadability; does not invent a server map or tile IDs.
"""
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE=Path(r'C:\Program Files (x86)\TIOnline\base')


if __name__=='__main__':
    source=BASE/'ground.xml'
    grounds=[]
    for ground in ET.parse(source).getroot():
        brushes=[]
        for brush in ground:
            relative=Path('setting')/brush.attrib['filename'].replace('\\','/')
            path=BASE/relative
            brushes.append({'path':relative.as_posix(),'layer':int(brush.attrib['layer']),
                            'exists':path.is_file(),
                            'sha256':hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None})
        grounds.append({'name':ground.attrib['name'],'id':int(ground.attrib['id']),
                        'brushes':brushes,'missing_count':sum(not b['exists'] for b in brushes)})
    result={'method':__doc__,'base':str(BASE),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
            'grounds':grounds}
    (ROOT/'evidence/battle_ground_resources.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print('Ground dependency counts:',[(g['id'],len(g['brushes']),g['missing_count']) for g in grounds])
