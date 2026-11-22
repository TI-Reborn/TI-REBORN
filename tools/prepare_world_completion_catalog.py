"""Prepare the bounded world catalogue from observed server/client sources.

Writes only stage8 runtime XML, client candidate XML and catalog.json. Existing
1..17 rows outside 4/7/10 are preserved byte for byte in each distinct source.
No local diagnostic catalogue, territory policy, database or installed client
is changed. New coordinates/IDs are explicit world_completion.json policy.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT/'reports/gameplay-completion/stage8-world'
POLICY = ROOT/'config/world_completion.json'
CLIENT_PATH = 'base/shared config/zones.xml'
SOURCE_XML_SHA = 'f707e1a4d077bd04e4643801f1c8a0ec4319779b71688dac8338951c3342f2d1'
SERVER_XML_SHA = 'd89f4dbdf9d784cea5fe3b3725110004cbce42775469b7c8ffbb23051f1f1f7d'
CHANGED = (4, 7, 10)
ADDED = (18, 19, 20, 21, 22)
CLONES = {18:8, 19:11, 20:12, 21:6, 22:12}
ROW = re.compile(rb'  <town\b[^>]*\bid="([0-9]+)"[^>]*>.*?</town>', re.S)


def sha(raw): return hashlib.sha256(raw).hexdigest()


def folder_checked(folder):
    path = Path(folder).resolve()
    if path != FOLDER.resolve():
        raise ValueError('Only the bounded stage8 report folder is writable')
    return path


def rows(raw, count):
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= 50000 or b'<!' in raw:
        raise ValueError('Unsafe or oversized zones XML')
    root = ET.fromstring(raw)
    if root.tag != 'towns' or root.attrib or len(root) != count:
        raise ValueError('Unexpected towns catalogue')
    result = {}
    for node in root:
        identity = int(node.attrib['id'])
        if (node.tag != 'town' or set(node.attrib) != {'id','name'}
                or identity in result or not node.attrib['name']):
            raise ValueError('Invalid or duplicate town identity')
        keys = set()
        for value in node:
            if (value.tag != 'value' or set(value.attrib) != {'key','val'}
                    or value.attrib['key'] in keys or len(value)):
                raise ValueError('Invalid or duplicate town property')
            keys.add(value.attrib['key'])
        result[identity] = node
    if list(result) != list(range(1,count+1)):
        raise ValueError('Native towns require ordered contiguous id-1 lookup')
    return result


def values(node): return {v.attrib['key']:v.attrib['val'] for v in node}


def semantic(node):
    return node.tag, tuple(sorted(node.attrib.items())), tuple(semantic(v) for v in node)


def set_value(node, key, value):
    found = next((v for v in node if v.get('key') == key), None)
    if found is None: found = ET.SubElement(node,'value',key=key)
    found.set('val',str(value))


def checked_policy(policy):
    if policy.get('version') != 1 or [r.get('id') for r in policy['locations']] != [*CHANGED,*ADDED]:
        raise ValueError('Unexpected bounded world policy identities')
    for r in policy['locations']:
        bounds, levels = r['bounds'], r['levels']
        if (r['kind'] not in ('town','base') or len(bounds) != 4
                or any(type(n) is not int or not -512 <= n <= 511 for n in bounds)
                or bounds[0] >= bounds[2] or bounds[1] >= bounds[3]
                or bounds[2]-bounds[0] != bounds[3]-bounds[1]
                or len(levels) != 2 or any(type(n) is not int for n in levels)
                or not 1 <= levels[0] <= levels[1] <= 20
                or type(r['max_upgrade']) is not int or not 0 <= r['max_upgrade'] <= 255
                or not re.fullmatch('loc_[a-z_]+',r['background'])
                or any(type(r[k]) is not bool for k in ('carry_items','arena','capture','prison_only'))):
            raise ValueError('Invalid native world policy geometry/levels/flags')
    return policy


def merge(raw, policy):
    source = rows(raw,17); policy = checked_policy(policy)
    patches = {}
    for rule in policy['locations']:
        identity = rule['id']
        node = deepcopy(source[identity if identity in CHANGED else CLONES[identity]])
        node.attrib.update(id=str(identity),name=rule['name'])
        x1,y1,x2,y2 = rule['bounds']
        updates = dict(enabled=1,type=rule['kind'],background=rule['background'],
            x1=x1,y1=y1,x2=x2,y2=y2,size=x2-x1,minlevel=rule['levels'][0],
            maxlevel=rule['levels'][1],drop='false',privateStore='false',
            arena=str(rule['arena']).lower(),dragin=str(rule['carry_items']).lower(),
            dragInMaxEnhance=rule['max_upgrade'],IsTraining=str(rule['profile']=='assault_training').lower(),
            rankBonus=10 if identity==18 else 0)
        if rule['kind']=='base' or rule['prison_only']:
            updates.update(shop='false',market='false',mercShop='false')
        if rule['kind']=='base': updates['assaultMap']=rule['assault_map']
        for key,value in updates.items(): set_value(node,key,value)
        node.tail = None; ET.indent(node,space='  ',level=1)
        patches[identity] = b'  '+ET.tostring(node,encoding='utf-8')
    matched = {int(m[1]):m[0] for m in ROW.finditer(raw)}
    if set(matched) != set(source):
        raise ValueError('Unknown source XML layout; preserve original rows')
    output = ROW.sub(lambda m:patches.get(int(m[1]),m[0]),raw)
    marker = b'</towns>'
    if output.count(marker) != 1: raise ValueError('Unexpected towns closing element')
    output = output.replace(marker,b'\n'.join(patches[i] for i in ADDED)+b'\n'+marker)
    after = rows(output,22)
    changed = [i for i in source if semantic(source[i]) != semantic(after[i])]
    if changed != list(CHANGED): raise ValueError('Unrelated source town changed')
    after_raw = {int(m[1]):m[0] for m in ROW.finditer(output)}
    if any(matched[i] != after_raw[i] for i in source if i not in CHANGED):
        raise ValueError('Foreign source town bytes changed')
    # Overlap at the old MO Base/Mine14 rectangle is removed. Every amended
    # or new rectangle must be disjoint from all other original town bounds.
    rectangles = {i:tuple(int(values(n)[k]) for k in ('x1','y1','x2','y2')) for i,n in after.items()}
    for identity in (*CHANGED,*ADDED):
        a = rectangles[identity]
        for other,b in rectangles.items():
            if identity != other and max(a[0],b[0]) < min(a[2],b[2]) and max(a[1],b[1]) < min(a[3],b[3]):
                raise ValueError(f'World location {identity} overlaps {other}')
    return output


def prepare(folder=FOLDER):
    folder = folder_checked(folder)
    source = (folder/'client/source/zones.xml').read_bytes()
    server = (folder/'source/zones_diagnostic.xml').read_bytes()
    observation = json.loads((folder/'client/source/observation.json').read_bytes())
    manifest = observation['manifest']; record = next(r for r in manifest['files'] if r['path']==CLIENT_PATH)
    if (manifest['schema'] != 1 or manifest['version'] != '2026.10.08.4'
            or record != observation['client_record'] or record.get('seed') is not False
            or record['sha256'] != SOURCE_XML_SHA or sha(source) != SOURCE_XML_SHA
            or record['size'] != len(source) or sha(server) != SERVER_XML_SHA):
        raise ValueError('Exact observed hosted sources required')
    policy_raw = POLICY.read_bytes(); policy = checked_policy(json.loads(policy_raw))
    client_new,server_new = merge(source,policy),merge(server,policy)
    outputs = {'client/candidate/zones.xml':client_new,'runtime/evidence/zones_diagnostic.xml':server_new}
    for name,raw in outputs.items():
        path = folder/name; path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(raw)
    report = dict(passed=True,source_version=manifest['version'],new_version='2026.10.08.5',
        client_path=CLIENT_PATH,source_client_sha256=sha(source),source_runtime_sha256=sha(server),
        policy_sha256=sha(policy_raw),source_territories_sha256=sha((folder/'source/territories.json').read_bytes()),
        observation_sha256=sha((folder/'client/source/observation.json').read_bytes()),
        candidate_sha256=sha(client_new),candidate_size=len(client_new),runtime_sha256=sha(server_new),
        changed_existing_ids=list(CHANGED),added_ids=list(ADDED),contiguous_ids=list(range(1,23)),
        clones={str(k):v for k,v in CLONES.items()},foreign_rows_preserved_byte_for_byte=True,
        distinct_original_sources_preserved=True,database_opened=False,installed_client_changed=False,
        local_diagnostic_changed=False,territory_policy_changed=False,published=False,
        location_provenance=[dict(id=r['id'],source=r['source']) for r in policy['locations']])
    (folder/'catalog.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--folder',type=Path,default=FOLDER)
    print(json.dumps(prepare(parser.parse_args().folder),indent=2))
