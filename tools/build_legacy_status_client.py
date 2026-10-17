"""Prepare the frozen .2 Silver plus thirteen native textures, without publishing."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import struct
import sys
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import publish_legacy_status_client as release


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def immutable(path, raw):
    if not release.PUBLISHER.no_symlinks(path):
        raise ValueError('Build paths must be regular')
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError('Existing immutable build differs: ' + str(path))
    else:
        with path.open('xb') as output:
            output.write(raw)


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def negative_checks(package, old, new, payloads):
    """Exercise scope/preservation rejections in the literal remote validator."""
    ns = dict(json=json,hashlib=hashlib,re=re,struct=struct,zlib=zlib,
              PurePosixPath=PurePosixPath,pe_at=release.PUBLISHER.pe_at,sha=sha,
              MANIFEST_SHA=release.MANIFEST_SHA,PREVIOUS_VERSION=release.PREVIOUS_VERSION,
              VERSION=release.VERSION,SILVER_SHA=release.SILVER_SHA,
              SILVER_BYTES=release.SILVER_BYTES,BASELINE_RECORDS=release.BASELINE_RECORDS,
              TI_SHA=release.PUBLISHER.TI_SHA,TI_BYTES=release.PUBLISHER.TI_BYTES,
              AUTH_SPANS=release.PUBLISHER.AUTH_SPANS)
    exec(release.PUBLISHER.VALIDATION, ns)
    rejected = []

    def reject(name, action):
        try:
            action()
        except (ValueError, KeyError, TypeError):
            rejected.append(name)
        else:
            raise ValueError('Invalid release was accepted: ' + name)

    def identity(value):
        raw = encoded(value)
        return ns['package_identity'](raw, sha(raw))

    mutations = []
    def altered(name, change):
        value = copy.deepcopy(package)
        change(value)
        mutations.append((name,value))

    altered('missing asset', lambda p:p['files'].pop())
    altered('extra asset', lambda p:p['files'].append(dict(p['files'][-1],path='base/pda/extra.png')))
    altered('duplicate path', lambda p:p['files'].__setitem__(2,copy.deepcopy(p['files'][1])))
    altered('path traversal', lambda p:p['files'][1].__setitem__('path','base/../secret.png'))
    altered('source traversal', lambda p:p['files'][1].__setitem__('source','../secret.png'))
    altered('case collision', lambda p:p['files'][1].__setitem__('path',p['files'][1]['path'].upper()))
    altered('wrong texture hash', lambda p:p['files'][1].__setitem__('sha256','0'*64))
    altered('wrong texture size', lambda p:p['files'][1].__setitem__('size',p['files'][1]['size']+1))
    altered('unreviewed texture kind', lambda p:p['files'][1].__setitem__('kind','icon_image'))
    altered('wrong Silver hash', lambda p:p['files'][0].__setitem__('sha256','0'*64))
    altered('wrong combined review', lambda p:p['native_review']['changes'][0].__setitem__('purpose','unreviewed patch'))
    altered('wrong append review', lambda p:p['native_review'].__setitem__('appended_size',0))
    altered('TI replacement', lambda p:p['files'][0].__setitem__('path','ti.exe'))
    altered('wrong release', lambda p:p.__setitem__('version','2026.10.11.3'))
    for name,value in mutations:
        reject(name, lambda value=value:identity(value))
    reject('wrong package pin', lambda:ns['package_identity'](encoded(package),'0'*64))
    for name,change in (
        ('unrelated record changed', lambda m:m['files'][100].__setitem__('size',m['files'][100]['size']+1)),
        ('record added', lambda m:m['files'].append(dict(m['files'][-1],path='base/extra.png'))),
        ('record order changed', lambda m:m['files'].reverse()),
        ('candidate seed changed', lambda m:next(x for x in m['files'] if x['path']=='silver.dll').__setitem__('seed',True)),
    ):
        manifest=json.loads(new)
        change(manifest)
        reject(name,lambda manifest=manifest:ns['manifest_transition'](old,encoded(manifest),package))
    source = release.source_blob('silver.dll').read_bytes()
    native = bytearray(payloads['silver.dll'])
    native[2000] ^= 1
    reject('undeclared native byte changed', lambda:ns['native_preserved'](source,bytes(native),package['native_review']))
    texture = next(x for x in package['files'] if x['path'].endswith('ground_military_base_a.tga'))
    before = release.source_blob(texture['path']).read_bytes()
    after = bytearray(payloads[texture['path']])
    after[21] ^= 1  # Native TGA first alpha byte; color changes remain permitted.
    reject('native texture alpha changed',lambda:ns['validate_replacement'](before,bytes(after)))
    after = bytearray(payloads[texture['path']])
    after[12] ^= 1
    reject('native texture dimensions changed',lambda:ns['validate_replacement'](before,bytes(after)))
    wrong_source=bytearray(before)
    wrong_source[18] ^= 1
    reject('wrong prior texture source',lambda:ns['blob_identity'](texture,payloads[texture['path']],bytes(wrong_source),package['native_review']))
    return rejected


def main():
    publisher = release.PUBLISHER
    client = release.FOLDER / 'client'
    source = release.source_blob('silver.dll').read_bytes()
    original = (ROOT/'reports/gameplay-completion/legacy-lobbies-20261011/client/silver.dll').read_bytes()
    if source != original or (sha(source),len(source)) != (release.SILVER_SHA,release.SILVER_BYTES):
        raise ValueError('Reviewed original and actual public prior Silver differ')
    native = release.NATIVE.read_bytes()
    review_raw = release.NATIVE_REVIEW.read_bytes()
    if (sha(native),len(native),sha(review_raw)) != (release.NATIVE_SHA,release.NATIVE_BYTES,release.NATIVE_REVIEW_SHA):
        raise ValueError('Immutable final native composition changed')
    review = json.loads(review_raw)
    preserved = publisher.native_preserved(source,native,review)
    prefix = 'release-' + release.VERSION
    files = [dict(path='silver.dll',source=prefix+'/silver.dll',sha256=sha(native),size=len(native),kind='native')]
    immutable(client/files[0]['source'],native)
    contracts = {}
    for row in release.pinned_inventory():
        name = row['path']
        candidate_path = release.FOLDER/'textures/candidate'/name
        if not publisher.no_symlinks(candidate_path):
            raise ValueError('Texture candidate must be regular')
        data = candidate_path.read_bytes()
        item = dict(path=name,source=prefix+'/assets/'+name,sha256=row['sha256'],size=row['size'],kind='native_texture')
        contracts[name] = publisher.blob_identity(item,data,release.source_blob(name).read_bytes(),review)
        immutable(client/item['source'],data)
        files.append(item)
    package = dict(schema=1,previous_version=release.PREVIOUS_VERSION,version=release.VERSION,
                   baseline_manifest_sha256=release.MANIFEST_SHA,selection=dict(fix=release.FIX),
                   native_review=review,files=files)
    raw = encoded(package)
    package_path = client/'package.json'
    immutable(package_path,raw)
    validated,payloads=release.load_package(package_path,sha(raw))
    payload=publisher.make_payload(package_path,sha(raw),'inspect',baseline=release.BASELINE)
    old=release.BASELINE.read_bytes()
    new=__import__('base64').b64decode(payload['after_manifest'],validate=True)
    transition=publisher.manifest_transition(old,new,validated)
    negatives=negative_checks(validated,old,new,payloads)
    immutable(client/'after-manifest.json',new)
    proof=dict(passed=True,version=release.VERSION,package_sha256=sha(raw),manifest_sha256=sha(new),
               source_sha256=sha(source),candidate_sha256=sha(native),candidate_bytes=len(native),
               texture_inventory_sha256=release.INVENTORY_SHA,texture_contract_sha256=release.CONTRACT_SHA,
               native_review_sha256=sha(review_raw),preservation=preserved,transition=transition,
               textures=contracts,negative_checks=len(negatives),rejected_cases=negatives,
               remote_validation_literal=True,hosted_mutations=0,published=False,
               graphical_acceptance=False,local_player_files_read=False,
               source_code_sha256={str(Path(module.__file__).relative_to(ROOT)).replace('\\','/'):sha(Path(module.__file__).read_bytes())
                                   for module in (release,sys.modules[__name__])})
    immutable(client/'package-validation.json',encoded(proof))
    print(json.dumps({key:proof[key] for key in ('passed','version','package_sha256','candidate_sha256','manifest_sha256','negative_checks','published')},indent=2))


if __name__ == '__main__':
    main()
