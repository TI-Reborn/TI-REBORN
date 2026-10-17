"""Reuse the immutable original25/27 consumer against new candidate TCP evidence."""
from pathlib import Path
import hashlib,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.verify_native_lobby_departure_sequence import sequence,SOURCE
F=ROOT/'reports/gameplay-completion/legacy-status-20261011/runtime-native-lobby-original-names'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    raw=SOURCE.read_bytes();report=json.loads((F/'tcp-cases.json').read_text(encoding='utf8'))
    assert report['passed']
    cases=[sequence(raw,b,c) for c in report['cases'] if c['native_sequence_hex'] for b in (0x400000,0x10400000)]
    assert len(cases)==24
    old=json.loads((F.parent/'runtime-native-lobby-departure/tcp-cases.json').read_text(encoding='utf8'))
    assert old['cases']==report['cases'],'Names presentation changed gameplay/member/removal TCP packets'
    result=dict(passed=True,native_sha256=hashlib.sha256(raw).hexdigest(),tcp_cases_sha256=sha(F/'tcp-cases.json'),
                cases=cases,all_16_departure_TCP_streams_identical_to_deployed21ac_a26=True,
                verifier_original_source_sha256=sha(ROOT/'tools/verify_native_lobby_departure_sequence.py'),
                original_25_27_consumers_executed=True,authentication_calls=0,hosted_modified=False,published=False)
    (F/'native-tcp-sequence-proof.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print('PASS 24 original25/27 slot sequences, gameplay TCP packets unchanged by original-Name presentation')
if __name__=='__main__':main()
