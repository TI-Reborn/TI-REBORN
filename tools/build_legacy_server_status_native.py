"""Reconstruct the immutable status/refresh candidate and exact public review."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import struct
import sys

import pefile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from deploy import client_server_list_status as status
from deploy import client_server_list_freshness as freshness
from tools.hosted_graphical_qa_bridge import SPANS
from tools.publish_battle_icon_centering_remote import VALIDATION, AUTH_SPANS
from tools.publish_ui_modernization_remote import pe_at

FOLDER=ROOT/'reports/gameplay-completion/legacy-status-20261011'
FINAL_SHA='853feb6a3803078ffaf1570969c8432bce37f8c20593acbadcdb5a68f798f3a1'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def build():
    source=(ROOT/'reports/gameplay-completion/legacy-lobbies-20261011/client/silver.dll').read_bytes()
    intermediate=status.patch(source); candidate=freshness.patch(intermediate)
    assert sha(candidate)==FINAL_SHA
    assert candidate==(FOLDER/'client-freshness/silver.dll').read_bytes()
    declarations=[]
    for review in (status.review(source,intermediate),freshness.review(intermediate,candidate)):
        declarations.extend((row['offset'],row['offset']+row['size'],row['purpose']) for row in review['changes'])
    merged=[]
    for start,end,purpose in sorted(declarations):
        if merged and start<=merged[-1][1]:
            previous=merged.pop(); merged.append((previous[0],max(previous[1],end),previous[2]))
        else:
            merged.append((start,end,purpose))
    review=dict(changes=[dict(offset=start,size=end-start,source_sha256=sha(source[start:end]),
                             candidate_sha256=sha(candidate[start:end]),purpose=purpose)
                         for start,end,purpose in merged],
                appended_size=len(candidate)-len(source),appended_sha256=sha(candidate[len(source):]))
    namespace=dict(json=json,re=re,struct=struct,hashlib=hashlib,PurePosixPath=PurePosixPath,
                   pe_at=pe_at,AUTH_SPANS=AUTH_SPANS,SILVER_BYTES=len(source))
    exec(VALIDATION,namespace)
    preservation=namespace['native_preserved'](source,candidate,review)
    before=pefile.PE(data=source); after=pefile.PE(data=candidate)
    try:
        protected=[]
        for name,va,size,expected in SPANS:
            old,new=before.get_data(va-0x400000,size),after.get_data(va-0x400000,size)
            assert old==new and sha(old)==expected,(name,hex(va))
            protected.append(dict(name=name,va=hex(va),size=size,sha256=expected,byte_identical=True))
        for name,va,size in (('original05',0x87c76c,71),('original06primitive_parser',0x87d1cc,450),
                             ('previous_availability_and_sampler_runtime',0xc73000,0x3000)):
            # The successful UI completion hook sits outside the protected
            # parser's first 450 bytes; original primitive read arithmetic stays.
            old,new=before.get_data(va-0x400000,size),after.get_data(va-0x400000,size)
            assert old==new,name
            protected.append(dict(name=name,va=hex(va),size=size,sha256=sha(old),byte_identical=True))
    finally:
        before.close(); after.close()
    proof=json.loads((FOLDER/'native-server-freshness.json').read_text(encoding='utf-8'))
    assert proof['status']=='PASS' and proof['candidate_sha256']==FINAL_SHA
    document=dict(passed=True,source_sha256=sha(source),source_bytes=len(source),
                  intermediate_sha256=sha(intermediate),candidate_sha256=sha(candidate),candidate_bytes=len(candidate),
                  native_review=review,preservation=preservation,protected_native_spans=protected,
                  verification_report='native-server-freshness.json',
                  verification_sha256=sha((FOLDER/'native-server-freshness.json').read_bytes()),
                  row_cases=proof['row_case_count'],temporal_cases=proof['temporal_case_count'],
                  real_graphical_clients=0,published=False,
                  source_code_sha256={str(Path(m.__file__).relative_to(ROOT)):sha(Path(m.__file__).read_bytes())
                                      for m in (status,freshness)})
    for filename,value in (('combined-review.json',review),('native-composition.json',document)):
        path=FOLDER/'client-freshness'/filename
        raw=(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
        if path.exists():
            assert path.read_bytes()==raw,'Immutable review differs: '+filename
        else:
            with path.open('xb') as stream:
                stream.write(raw)
    print(json.dumps(dict(passed=True,candidate_sha256=FINAL_SHA,candidate_bytes=len(candidate),
                          combined_review_sha256=sha((FOLDER/'client-freshness/combined-review.json').read_bytes()),
                          auth_spans=len(SPANS),preservation=preservation),indent=2))
    return document


if __name__=='__main__':
    build()
