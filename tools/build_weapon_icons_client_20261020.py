"""Build an art-only client release from the exact live item XML and generated PNGs."""
import hashlib
import json
import re
import shutil
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/weapon-icons-20261020'
ASSETS=ROOT/'assets/weapon-icons-v1'
XML='base/shared config/items.xml'
VERSION='2026.10.20.5'
sha=lambda b:hashlib.sha256(b).hexdigest()


def semantic(node,without_image=False):
    return (node.tag,tuple(sorted(node.attrib.items())),(node.text or '').strip(),tuple(
        semantic(n,without_image) for n in node if not(without_image and n.tag=='value' and n.get('key')=='image')))


def build():
    old=(OUT/'manifest-before.json').read_bytes();manifest=json.loads(old)
    assert tuple(map(int,VERSION.split('.')))>tuple(map(int,manifest['version'].split('.')))
    rows={r['path']:r for r in manifest['files']}
    raw=(OUT/'source'/XML).read_bytes();assert sha(raw)==rows[XML]['sha256']
    catalog=json.loads((ASSETS/'catalog.json').read_text(encoding='utf-8'))['items']
    hosted=json.loads((OUT/'remote-source/config/weapon_catalog.json').read_text(encoding='utf-8'))['weapons']
    assert {str(i['id']) for i in catalog}==set(hosted) and len(catalog)==45
    root=ET.fromstring(raw);before={int(n.get('id')):n for n in ET.fromstring(raw)}
    nodes={int(n.get('id')):n for n in root};assert len(nodes)==len(root)==164
    files=[];mapping=[]
    for item in catalog:
        identity=item['id'];node=nodes[identity]
        assert node.get('name')==item['name']==hosted[str(identity)]['name']
        name=f'tio_wi_{identity}.png';path='base/items/'+name
        assert path not in rows and len(name)<32 and re.fullmatch(r'tio_wi_\d+\.png',name)
        source=ASSETS/'exports/64x32'/item['file'];png=source.read_bytes()
        assert png[:8]==b'\x89PNG\r\n\x1a\n' and png[16:24]==b'\0\0\0@\0\0\0 '
        image=next((n for n in node.findall('value') if n.get('key')=='image'),None)
        previous=image.get('val') if image is not None else None
        if image is None:image=ET.SubElement(node,'value',key='image')
        image.set('val',name)
        target=OUT/'client'/path;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
        files.append(dict(path=path,sha256=sha(png),size=len(png),seed=False))
        mapping.append(dict(id=identity,name=item['name'],previous_image=previous,image=name,
                            source=source.relative_to(ROOT).as_posix(),sha256=sha(png),size=[64,32]))
    ET.indent(root);candidate=ET.tostring(root,encoding='utf-8',xml_declaration=True)
    assert set(before)==set(nodes)
    assert all(semantic(before[i],True)==semantic(nodes[i],True) for i in before)
    changed=sorted(i for i in before if semantic(before[i])!=semantic(nodes[i]))
    assert changed==sorted(i['id'] for i in catalog)
    path=OUT/'client'/XML;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(candidate)
    record=dict(rows[XML]);record.update(sha256=sha(candidate),size=len(candidate),seed=False)
    manifest['files']=[record if r['path']==XML else r for r in manifest['files']]+files
    manifest['version']=VERSION
    new=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
    (OUT/'manifest.json').write_bytes(new)
    server_before=(OUT/'remote-source/evidence/items_diagnostic.xml').read_bytes()
    server_tree=ET.fromstring(server_before);server_nodes={int(n.get('id')):n for n in server_tree}
    for item in catalog:
        node=server_nodes[item['id']]
        image=next((n for n in node.findall('value') if n.get('key')=='image'),None)
        if image is None:image=ET.SubElement(node,'value',key='image')
        image.set('val',f'tio_wi_{item["id"]}.png')
    server_old={int(n.get('id')):n for n in ET.fromstring(server_before)}
    assert set(server_old)==set(server_nodes)
    assert all(semantic(server_old[i],True)==semantic(server_nodes[i],True) for i in server_old)
    assert sorted(i for i in server_old if semantic(server_old[i])!=semantic(server_nodes[i]))==changed
    ET.indent(server_tree);server_raw=ET.tostring(server_tree,encoding='utf-8',xml_declaration=True)
    server_path=OUT/'server/evidence/items_diagnostic.xml';server_path.parent.mkdir(parents=True,exist_ok=True);server_path.write_bytes(server_raw)
    result=dict(passed=True,version=VERSION,previous_version=json.loads(old)['version'],
                manifest_before_sha256=sha(old),manifest_sha256=sha(new),
                xml_before_sha256=sha(raw),xml_sha256=sha(candidate),changed_item_ids=changed,
                only_item_image_fields_changed=True,all_other_existing_records_preserved=True,
                new_files=files,modified_files=[XML],mapping=mapping,
                executable_changes=False,server_changes=['evidence/items_diagnostic.xml'],
                server_before_sha256=sha(server_before),server_sha256=sha(server_raw),
                player_data_changes=False)
    (OUT/'build.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=True,version=VERSION,items=len(mapping),new_files=len(files),modified_files=[XML])))


if __name__=='__main__':build()
