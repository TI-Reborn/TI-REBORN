"""Read-only inherited .3 arena proof bound to the exact public .11 manifest."""
import copy
import hashlib
import json
from pathlib import Path

from tools import arena_boundaries_validation as boundaries
from tools.arena_boundaries_release import records, require
from tools.hosted_stage9_graphical_qa_revision3 import https

ROOT=Path(__file__).resolve().parents[1]
CURRENT_SHA='b05f5ff717480e540dde4c13d152e2169861cc29d86801ee4ee591da8f079e6f'
BOUNDARY_SHA='ca72b595edb0d999bd9618aee10abac36747755462bf60487449b2ed2720dd8d'
FROZEN=ROOT/'reports/arena-boundaries-implementation/client-release/manifest.json'


def asset_path(path):
    return path.startswith(('base/maps/as_', 'base/setting/arena_surroundings/',
                            'base/setting/arena_boundaries/'))


def inheritance(manifest):
    raw=FROZEN.read_bytes()
    require(hashlib.sha256(raw).hexdigest()==BOUNDARY_SHA,'Frozen published .3 manifest differs')
    old=json.loads(raw)
    require(old['version']=='2026.10.07.3' and manifest['version']=='2026.10.09.11',
            'Unexpected arena inheritance versions')
    original,current=records(old),records(manifest)
    scope={p for p in original if asset_path(p)}
    require(scope=={p for p in current if asset_path(p)},'Inherited arena asset scope changed')
    require(all(original[p]==current[p] for p in scope),'A published inherited arena record changed')
    return old,len(scope)


def published_scene(host,manifest,scene,size,*,fetch=None):
    require(host=='185.184.42.88','Unexpected public UI battle host')
    raw=https('https://'+host+'/updates/manifest.json',8*1024*1024)
    require(hashlib.sha256(raw).hexdigest()==CURRENT_SHA and json.loads(raw)==manifest,
            'Current public .11 manifest differs')
    frozen,count=inheritance(manifest)
    actual=records(manifest)
    def checked_fetch(record):
        require(actual.get(record['path'])==record,'Requested inherited record is absent from actual .11')
        blob=(https('https://'+host+'/updates/blobs/'+record['sha256'],record['size']+1)
              if fetch is None else fetch(record))
        require(len(blob)==record['size'] and hashlib.sha256(blob).hexdigest()==record['sha256'],
                'Actual .11 inherited resource differs from its exact record')
        return blob
    # The complete frozen .3 manifest is an independently SHA-pinned input to
    # its unchanged strict append/B1/PNG/alpha verifier. Each fetched record
    # also must be byte-identical to the actual current .11 published record.
    result=boundaries.published_boundary_scene(host,frozen,scene,size,fetch=checked_fetch)
    result.update(actual_client_version=manifest['version'],actual_manifest_sha256=CURRENT_SHA,
                  inherited_boundary_manifest_sha256=BOUNDARY_SHA,
                  all_inherited_arena_records_exact=count,
                  actual_public_assets_verified=True)
    return result


def self_test():
    current=json.loads((ROOT/'reports/ui-modernization/baseline/manifest.json').read_bytes())
    old,count=inheritance(current);rejected=0
    path=next(r['path'] for r in old['files'] if asset_path(r['path']))
    for kind in ('changed_sha','removed','added_foreign','wrong_version'):
        changed=copy.deepcopy(current)
        if kind=='changed_sha':next(r for r in changed['files'] if r['path']==path)['sha256']='0'*64
        elif kind=='removed':changed['files']=[r for r in changed['files'] if r['path']!=path]
        elif kind=='added_foreign':changed['files'].append(dict(path='base/maps/as_foreign.s',size=1,sha256='0'*64))
        else:changed['version']='2026.10.07.1'
        try:inheritance(changed)
        except RuntimeError:rejected+=1
        else:raise AssertionError('Unsafe asset inheritance was accepted')
    assert rejected==4
    return dict(result='PASS',offline_cases=5,inherited_records=count,
                rejected_asset_scope_or_record_changes=4,network_used=False,hosted_mutations=False)
