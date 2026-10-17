"""Encode the final project agreement and build a scoped one-file legacy release."""
from __future__ import annotations

import argparse
import base64
import copy
import json
from pathlib import Path, PurePosixPath
import re
import sys
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import publish_legacy_project_agreement_client as release
from tools.verify_legacy_project_agreement_native import native_crc32


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def prepare(canonical, draft=False):
    canonical = canonical.resolve()
    if not release.regular(canonical) or not (canonical.is_relative_to(release.FOLDER) or canonical == (ROOT/'web/src/lib/user-agreement.json').resolve()):
        raise ValueError('Use the project canonical JSON or scoped canonical UTF8 text')
    canonical_raw=canonical.read_bytes()
    accepted_pins=None
    if not draft:
        accepted_pins=release.canonical_inputs()
        if canonical!=release.CANONICAL.resolve():raise ValueError('Use only the frozen accepted canonical JSON for the final native agreement')
    if canonical.suffix.lower()=='.json':
        document=json.loads(canonical_raw)
        locale=document['locales']['ru']
        if document['project']!='TI-REBORN' or [section['id'] for section in locale['sections']]!=list(range(1,13)):
            raise ValueError('Canonical Russian agreement schema/section order differs')
        paragraphs=[locale['title'],locale['editionLabel'],locale['intro']]
        for section in locale['sections']:
            paragraphs.append(str(section['id'])+'. '+section['title'])
            paragraphs.extend(section['paragraphs'])
        if any(not isinstance(p,str) or not p or '\n' in p or '\r' in p for p in paragraphs):
            raise ValueError('Canonical agreement must use explicit nonempty paragraph records')
        original_text='\n\n'.join(paragraphs)+'\n'
    else:original_text=canonical_raw.decode('utf-8-sig')
    if not draft and original_text!=release.CANONICAL_TEXT.read_text(encoding='utf-8'):
        raise ValueError('Russian paragraphs derived from JSON differ from the accepted plain text')
    text = original_text.replace('\r\n', '\n').replace('\r', '\n')
    if not text.endswith('\n'):
        text += '\n'
    raw = text.replace('\n', '\r\n').encode('cp1251', errors='strict')
    if not 1024 <= len(raw) <= 65536 or any(ord(c) < 32 and c not in '\r\n' for c in text):
        raise ValueError('Final native agreement text/control bounds invalid')
    if any(c in text for c in ('\u2013','\u2014','\u2018','\u2019','\u201c','\u201d')):
        raise ValueError('Use original-font ASCII hyphens and quotation marks in the canonical wording')
    source = (release.CLIENT / 'source/assets' / release.RULES_PATH).read_bytes()
    image = (release.CLIENT / 'source/silver.dll').read_bytes()
    if (release.sha(source),len(source)) != (release.RULES_SOURCE_SHA,release.RULES_SOURCE_BYTES) or (release.sha(image),len(image)) != (release.SILVER_SHA,release.SILVER_BYTES):
        raise ValueError('Actual pinned published3 rules and native image required')
    crc = {name: native_crc32(image,value) for name,value in [('source',source),('candidate',raw)]}
    if crc['source'] != zlib.crc32(source)&0xffffffff or crc['candidate'] != zlib.crc32(raw)&0xffffffff or crc['source'] == crc['candidate']:
        raise ValueError('Native agreement CRC must change and match independent implementation')
    if canonical.read_bytes()!=canonical_raw:raise ValueError('Canonical wording changed during encoding')
    draft_folder=release.CLIENT/'drafts'/release.sha(canonical_raw)
    candidate = (draft_folder if draft else release.CLIENT / 'candidate') / release.RULES_PATH
    release.immutable(candidate,raw)
    review = dict(passed=True,source_sha256=release.sha(source),source_bytes=len(source),candidate_sha256=release.sha(raw),candidate_bytes=len(raw),
                  canonical_utf8_path=canonical.relative_to(ROOT).as_posix(),canonical_utf8_sha256=release.sha(canonical_raw),
                  encoding='windows-1251',line_endings='CRLF',lines=raw.count(b'\r\n'),max_line_chars=max(map(len,text.splitlines())),
                  native_crc32=crc,original_reacceptance_required=True,stored_acceptance_modified=False,
                  unchanged_silver_sha256=release.sha(image),replacement_scope=[release.RULES_PATH],hosted_mutations=0,
                  graphical_acceptance=False,local_player_files_read=False,canonical_review_pending=draft,
                  accepted_canonical_source_pins=accepted_pins)
    release.immutable(draft_folder/'agreement-review.json' if draft else release.REVIEW,encoded(review))
    print(json.dumps(dict(passed=True,candidate_path=candidate.relative_to(ROOT).as_posix(),candidate_sha256=release.sha(raw),candidate_bytes=len(raw),review_sha256=release.sha(encoded(review)),canonical_review_pending=draft),indent=2))


def negative_checks(base,package,old,new,raw,source):
    rejected=[]
    def reject(name,action):
        try:action()
        except (ValueError,KeyError,TypeError,UnicodeError):rejected.append(name)
        else:raise ValueError('Out-of-scope agreement change accepted: '+name)
    def identity(value):
        data=encoded(value);return base.package_identity(data,release.sha(data))
    for name,change in (
        ('missing agreement',lambda p:p['files'].clear()),
        ('extra asset',lambda p:p['files'].append(dict(p['files'][0],path='base/russian.lng'))),
        ('DLL replacement',lambda p:p['files'][0].__setitem__('path','silver.dll')),
        ('executable replacement',lambda p:p['files'][0].__setitem__('path','ti.exe')),
        ('acceptance configuration replacement',lambda p:p['files'][0].__setitem__('path','base/config.cfg')),
        ('path traversal',lambda p:p['files'][0].__setitem__('path','base/../rules.txt')),
        ('source traversal',lambda p:p['files'][0].__setitem__('source','../rules.txt')),
        ('case variation',lambda p:p['files'][0].__setitem__('path','base/RULES.txt')),
        ('wrong exact hash',lambda p:p['files'][0].__setitem__('sha256','0'*64)),
        ('wrong exact size',lambda p:p['files'][0].__setitem__('size',p['files'][0]['size']+1)),
        ('unsupported resource kind',lambda p:p['files'][0].__setitem__('kind','native')),
        ('native change metadata',lambda p:p.__setitem__('native_review',{})),
        ('wrong release',lambda p:p.__setitem__('version','2026.10.11.5')),
    ):
        value=copy.deepcopy(package);change(value);reject(name,lambda value=value:identity(value))
    reject('wrong package pin',lambda:base.package_identity(encoded(package),'0'*64))
    for name,change in (
        ('another manifest record changed',lambda m:m['files'][100].__setitem__('size',m['files'][100]['size']+1)),
        ('record added',lambda m:m['files'].append(dict(m['files'][-1],path='base/extra.txt'))),
        ('record removed',lambda m:m['files'].pop()),
        ('record order changed',lambda m:m['files'].reverse()),
        ('rules seed changed',lambda m:next(x for x in m['files'] if x['path']==release.RULES_PATH).__setitem__('seed',True)),
    ):
        value=json.loads(new);change(value);reject(name,lambda value=value:base.manifest_transition(old,encoded(value),package))
    item=package['files'][0]
    reject('actual prior source differs',lambda:base.blob_identity(item,raw,source+b' ',None))
    reject('UTF8 native encoding refused',lambda:base.agreement_identity(raw.decode('cp1251').encode('utf-8')))
    reject('candidate content changed',lambda:base.agreement_identity(raw+b' '))
    reject('LF-only native text refused',lambda:base.agreement_identity(raw.replace(b'\r\n',b'\n')))
    reject('stored acceptance metadata refused',lambda:identity(dict(package,last_user_agreement_hash=0)))
    return rejected


def build():
    base=release.publisher()
    raw=(release.CLIENT/'candidate'/release.RULES_PATH).read_bytes()
    source=(release.CLIENT/'source/assets'/release.RULES_PATH).read_bytes()
    frozen=release.review()
    if (release.sha(raw),len(raw))!=(frozen['candidate_sha256'],frozen['candidate_bytes']):
        raise ValueError('Final canonical agreement freeze differs')
    item=dict(path=release.RULES_PATH,source='release-'+release.VERSION+'/assets/'+release.RULES_PATH,
              sha256=release.sha(raw),size=len(raw),kind='project_agreement')
    release.immutable(release.CLIENT/item['source'],raw)
    package=dict(schema=1,previous_version=release.PREVIOUS_VERSION,version=release.VERSION,
                 baseline_manifest_sha256=release.MANIFEST_SHA,selection=dict(fix=release.FIX),native_review=None,files=[item])
    package_raw=encoded(package);package_path=release.CLIENT/'package.json'
    release.immutable(package_path,package_raw)
    validated,payloads=release.load_package(package_path,release.sha(package_raw))
    payload=base.make_payload(package_path,release.sha(package_raw),'inspect',baseline=release.BASELINE)
    old=release.BASELINE.read_bytes();new=base64.b64decode(payload['after_manifest'],validate=True)
    transition=base.manifest_transition(old,new,validated)
    negatives=negative_checks(base,validated,old,new,raw,source)
    release.immutable(release.CLIENT/'after-manifest.json',new)
    proof=dict(passed=True,version=release.VERSION,package_sha256=release.sha(package_raw),manifest_sha256=release.sha(new),
               agreement_review_sha256=release.REVIEW_SHA,source_sha256=release.sha(source),candidate_sha256=release.sha(raw),candidate_bytes=len(raw),
               transition=transition,agreement=base.blob_identity(item,raw,source,None),negative_checks=len(negatives),rejected_cases=negatives,
               remote_validation_literal=True,hosted_mutations=0,published=False,graphical_acceptance=False,
               stored_acceptance_modified=False,local_player_files_read=False,unchanged_native_record_sha256=release.SILVER_SHA,
               preserved_existing_records=release.BASELINE_RECORDS-1,publication_dependency_pins=release.DEPENDENCIES,
               accepted_canonical_source_pins=release.CANONICAL_INPUTS,native_loader_proof_sha256=release.NATIVE_PROOF_SHA,
               source_code_sha256={Path(module.__file__).relative_to(ROOT).as_posix():release.sha(Path(module.__file__).read_bytes()) for module in (release,sys.modules[__name__])})
    release.immutable(release.CLIENT/'package-validation.json',encoded(proof))
    print(json.dumps({key:proof[key] for key in ('passed','version','package_sha256','manifest_sha256','candidate_sha256','negative_checks','published')},indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare','build'))
    parser.add_argument('--canonical',type=Path)
    parser.add_argument('--draft',action='store_true')
    args=parser.parse_args()
    if args.action=='prepare':
        if not args.canonical:raise ValueError('Final canonical UTF8 agreement required')
        prepare(args.canonical,args.draft)
    else:build()


if __name__=='__main__':
    main()
