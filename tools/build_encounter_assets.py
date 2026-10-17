"""Add isolated infected-dog bindings to the exact published client resources."""
from pathlib import Path
import copy,hashlib,json,re,shutil,sys,xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
OUT=ROOT/'reports/dog-encounters/client'
BASE=Path(r'C:/Program Files (x86)/TIOnline/base')


def xml_items(data):
    root=ET.fromstring(data)
    for identity in (65489,65490):
        old=root.find(f"item[@id='{identity}']")
        if old is not None:root.remove(old)
    if root.find("item[@id='65490']") is None:
        body=copy.deepcopy(root.find("item[@id='65510']"));assert body is not None
        body.set('id','65490');body.set('name','infected dog body')
        body.find("value[@key='texture_1']").set('val','dog_infected.jpg');root.append(body)
    if root.find("item[@id='65489']") is None:
        bite=copy.deepcopy(root.find("item[@id='333']"));assert bite is not None
        bite.set('id','65489');bite.set('name','Infected Dog Bite')
        values={n.get('key'):n for n in bite.findall('value')}
        for key,val in {'p_dam':'12','rnd_dam':'6','actionPoints':'4','weight':'0','durability':'0'}.items():
            if key not in values:values[key]=ET.SubElement(bite,'value',key=key)
            values[key].set('val',val)
        from tools.normalize_weapon_xml import normalize
        normalize(bite,{**{n.get('key'):n.get('val') for n in bite.findall('value')},'item_id':'65489'})
        root.append(bite)
    ET.indent(root)
    return b"<?xml version='1.0' encoding='utf-8'?>\n"+ET.tostring(root,encoding='utf-8')+b'\n'


def main():
    manifest=json.loads((ROOT/'reports/dog-encounters/previous-client-manifest.json').read_text(encoding='utf-8'))
    records={r['path']:r for r in manifest['files']}
    sources=ROOT/'reports/dog-encounters/published-source'
    sources.mkdir(parents=True,exist_ok=True)
    # Original publication is authoritative. Download the three exact blobs first.
    import urllib.request
    for name in ('base/mobs.udf','base/animation.xml','base/shared config/items.xml'):
        record=records[name];p=sources/Path(name).name
        if not p.exists():
            with urllib.request.urlopen('https://185.184.42.88/updates/blobs/'+record['sha256'],timeout=30) as response:p.write_bytes(response.read())
        assert len(p.read_bytes())==record['size'] and hashlib.sha256(p.read_bytes()).hexdigest()==record['sha256']
    OUT.mkdir(parents=True,exist_ok=True)
    mobs=(sources/'mobs.udf').read_bytes()
    text=mobs.decode('cp1251')
    block=next(b for b in re.findall(r'\[mob\]\s*\{[^}]+\}',text) if re.search(r'\bid\s*=\s*5\s*;',b))
    assert not re.search(r'\bid\s*=\s*103\s*;',text)
    block=re.sub(r'\bid\s*=\s*5\s*;', 'id = 103;',block)
    block=block.replace('#Dog Alsatian','#Infected Feral Dog').replace('body = 65510;','body = 65490;').replace('default-weapon = 333;','default-weapon = 65489;')
    end=text.rfind('}');text=text[:end]+'\n  '+block+'\n'+text[end:]
    (OUT/'mobs.udf').write_bytes(text.encode('cp1251'))
    anim=ET.fromstring((sources/'animation.xml').read_bytes())
    assert anim.find("Race/r[@id='103']") is None
    ET.SubElement(anim.find('Race'),'r',id='103',Name='Dog')
    ET.indent(anim);(OUT/'animation.xml').write_bytes(ET.tostring(anim,encoding='utf-8',xml_declaration=True))
    (OUT/'items.xml').write_bytes(xml_items((sources/'items.xml').read_bytes()))
    server_items=ROOT/'evidence/items_diagnostic.xml'
    server_items.write_bytes(xml_items(server_items.read_bytes()))
    shutil.copyfile(ROOT/'assets/infected-dog-v1/dog_infected.jpg',OUT/'dog_infected.jpg')
    weapons_path=ROOT/'config/weapon_catalog.json';weapons=json.loads(weapons_path.read_text(encoding='utf-8'))
    bite=copy.deepcopy(weapons['weapons']['333'])
    bite.update(name='Infected Dog Bite',damage_base=12,damage_random=6,attack_ap=4)
    bite['source_fields'].update(item_id='65489',name='Infected Dog Bite',p_dam='12',rnd_dam='6',actionPoints='4',weight='0',durability='0')
    weapons['weapons']['65489']=bite;weapons.setdefault('npc_default_weapons',{})['103']=65489
    weapons_path.write_text(json.dumps(weapons,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(resource=103,body=65490,weapon=65489,files=[p.name for p in OUT.iterdir()])))

if __name__=='__main__':main()
