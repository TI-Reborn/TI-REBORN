"""Merge the reviewed item overlay into exact published XML and server catalogs."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import urllib.request
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'reports/gameplay-completion/stage3-items'

def sha(raw):return hashlib.sha256(raw).hexdigest()

def merge(raw,overlay):
    tree=ET.fromstring(raw);before={int(n.get('id')):n for n in tree}
    for identity,values in overlay['amendments'].items():
        item=before[int(identity)];nodes={v.get('key'):v for v in item.findall('value')}
        for key,value in values.items():
            if key not in nodes:nodes[key]=ET.SubElement(item,'value',key=key)
            nodes[key].set('val',value)
    for node in ET.parse(ROOT/'config/battle_item_catalog_extension.xml').getroot():
        if int(node.get('id')) in before:raise ValueError('New ID already in source XML')
        tree.append(deepcopy(node))
    ET.indent(tree)
    return ET.tostring(tree,encoding='utf-8',xml_declaration=True)

def main():
    source=FOLDER/'client/source';candidate=FOLDER/'client/candidate'
    source.mkdir(parents=True,exist_ok=True);candidate.mkdir(parents=True,exist_ok=True)
    overlay=json.loads((ROOT/'config/battle_item_catalog_extension.json').read_text(encoding='utf-8'))
    manifest_path=source/'manifest.json'
    origin='https://185.184.42.88/updates/'
    if not manifest_path.exists():
        with urllib.request.urlopen(origin+'manifest.json',timeout=30) as response:raw=response.read()
        manifest_path.write_bytes(raw)
    manifest=json.loads(manifest_path.read_bytes())
    item_record=next(r for r in manifest['files'] if r['path']=='base/shared config/items.xml')
    old_path=source/'items.xml'
    if not old_path.exists():
        with urllib.request.urlopen(origin+'blobs/'+item_record['sha256'],timeout=60) as response:raw=response.read()
        if sha(raw)!=item_record['sha256'] or len(raw)!=item_record['size']:raise ValueError('Published XML hash differs')
        old_path.write_bytes(raw)
    raw=old_path.read_bytes()
    if sha(raw)!=item_record['sha256']:raise ValueError('Stored XML source changed')
    assets={r['path']:r for r in manifest['files']}
    if any(p not in assets for p in overlay['assets']):raise ValueError('Item asset missing from update manifest')
    updated=merge(raw,overlay);(candidate/'items.xml').write_bytes(updated)
    old_diag=source/'items_diagnostic.xml'
    if not old_diag.exists():old_diag.write_bytes((ROOT/'evidence/items_diagnostic.xml').read_bytes())
    new_diag=merge(old_diag.read_bytes(),overlay)
    (ROOT/'evidence/items_diagnostic.xml').write_bytes(new_diag)
    weapon_path=ROOT/'config/weapon_catalog.json';weapons=json.loads(weapon_path.read_text(encoding='utf-8'))
    weapons['weapons'].update(overlay['weapon_catalog_entries'])
    weapons['item_effect_overlay']='config/battle_item_catalog_extension.json; new IDs are emulator policy'
    weapon_path.write_text(json.dumps(weapons,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    city_path=ROOT/'config/city_catalogs.json';city=json.loads(city_path.read_text(encoding='utf-8'))
    offers=city['item_categories']['0']
    # Smoke is an experimental legacy template without a price in the 2011 book.
    if not any(o['item_id']==318 for o in offers):
        offers.append(dict(unknown_u32_01=max(o['unknown_u32_01'] for o in offers)+1,
            unknown_u32_02=1,item_id=318,unknown_u32_03=180,durability=300,unknown_u8=0))
    premiums={o['item_id']:o for o in city['premium_items']}
    prices={24:10,35:100,**{o['id']:o['gold'] for o in overlay['items']}}
    for identity,price in prices.items():
        if price is None:raise ValueError('Missing reviewed premium price')
        duration=900 if identity==24 else 300 if identity in (5001,5002) else 1
        row=dict(offer_id=1000+identity,item_id=identity,pack_count=1,gold=price,durability=duration)
        if identity in premiums:
            old=premiums[identity]
            if old['gold']!=price:raise ValueError('Existing documented premium price differs')
            old['durability']=duration
        else:city['premium_items'].append(row)
    city['price_revision']=20261008
    city['battle_item_prices']='Manual printed64/79-83; smoke318180cr is explicit emulator policy, absent from book.'
    city_path.write_text(json.dumps(city,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    before={int(n.get('id')):ET.tostring(n) for n in ET.fromstring(raw)}
    after={int(n.get('id')):ET.tostring(n) for n in ET.fromstring(updated)}
    # Serialization whitespace is irrelevant; compare semantic trees.
    def semantics(n):return n.tag,tuple(sorted(n.attrib.items())),(n.text or '').strip(),tuple(semantics(c) for c in n)
    a={int(n.get('id')):semantics(n) for n in ET.fromstring(raw)}
    b={int(n.get('id')):semantics(n) for n in ET.fromstring(updated)}
    changed=sorted(i for i in a if a[i]!=b[i])
    if changed!=[24,35] or sorted(b.keys()-a.keys())!=overlay['new_ids']:raise ValueError('Unexpected catalog semantic change')
    report=dict(passed=True,version=manifest['version'],source_xml_sha256=sha(raw),candidate_xml_sha256=sha(updated),
        source_diagnostic_sha256=sha(old_diag.read_bytes()),candidate_diagnostic_sha256=sha(new_diag),
        changed_existing_items=changed,new_ids=overlay['new_ids'],published_assets_present=overlay['assets'],
        premium_prices=prices,smoke_credit_price_policy=180,original_cfg_modified=False)
    (FOLDER/'catalog.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))

if __name__=='__main__':main()
