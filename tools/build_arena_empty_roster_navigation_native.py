"""Freeze exact published853feb→native lobby navigation/colour presentation."""
from __future__ import annotations
import hashlib,json,re,struct,sys
from pathlib import Path,PurePosixPath
import pefile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from deploy import client_arena_empty_roster_navigation as patcher
from tools.verify_arena_empty_roster_navigation_native import FOLDER,SOURCE
from tools.hosted_graphical_qa_bridge import SPANS
from tools.publish_battle_icon_centering_remote import VALIDATION,AUTH_SPANS
from tools.publish_ui_modernization_remote import pe_at


def build():
 source=SOURCE.read_bytes();candidate=(FOLDER/'silver.dll').read_bytes();review=patcher.review(source,candidate)
 proof_path=FOLDER/'native-navigation-proof.json';proof=json.loads(proof_path.read_text(encoding='utf8'))
 assert proof['passed'] and proof['candidate_sha256']==patcher.sha(candidate)
 namespace=dict(json=json,re=re,struct=struct,hashlib=hashlib,PurePosixPath=PurePosixPath,pe_at=pe_at,
                AUTH_SPANS=AUTH_SPANS,SILVER_BYTES=len(source))
 exec(VALIDATION,namespace);preservation=namespace['native_preserved'](source,candidate,review)
 before=pefile.PE(data=source);after=pefile.PE(data=candidate);spans=[]
 try:
  guards=[(name,va,size,expected) for name,va,size,expected in SPANS]
  guards.extend((name,va,size,None) for name,va,size in (
   ('all_previous_availability_texture_status_freshness_runtime',0xc73000,0x5000),
   ('Survival_selected_predicate_and_tabs_positive_callback',0x9441c4,0x70),
   ('Survival_navigation_callback',0x944370,0x2a),
   ('Team_navigation_callback',0x9443d0,0x1e),('Wall_navigation_callback',0x944434,0x1e),
   ('selected_count31',0x87969c,0x27),('main_join_callback',0x873794,0x55),
   ('main_join_writer29',0xa089f0,0x60),('arena_search_callback',0x875118,0x21),
   ('arena_search_writerBA03',0x85f954,0x60),('original_list_requestBA01',0x85f918,0x38),
   ('BA02_parser_exact',0x85fa88,0x228),('full_main_lobby_renderer',0x877158,0x16da),
   ('integer_formatter4244B4',0x4244b4,0x27),('original05_request',0x87c76c,71)))
  for name,va,size,expected in guards:
   old,new=before.get_data(va-0x400000,size),after.get_data(va-0x400000,size)
   assert old==new,name
   digest=patcher.sha(old)
   if expected:assert digest==expected,name
   spans.append(dict(name=name,va=hex(va),size=size,sha256=digest,byte_identical=True))
 finally:before.close();after.close()
 report=dict(passed=True,source_sha256=patcher.sha(source),source_bytes=len(source),candidate_sha256=patcher.sha(candidate),
             candidate_bytes=len(candidate),native_review=review,preservation=preservation,protected_native_spans=spans,
             native_proof='native-navigation-proof.json',native_proof_sha256=patcher.sha(proof_path.read_bytes()),
             owned_readonly_original_gui_evidence='owned-c-rows-before-fix.json',
             owned_readonly_original_gui_evidence_sha256=patcher.sha((FOLDER/'owned-c-rows-before-fix.json').read_bytes()),
             metadata=patcher.metadata(),display_colours=dict(free_eligible_abgr='ff50e070',no_eligible_abgr='ff6060ff',full_or_searching_eligible_abgr='ff606060'),
             row_counts='Unchanged native members/capacity projection, integer formatting and full row renderer; BA02 backend mirror supplies actual humans',
             authenticated_gameplay_requests_unchanged=True,real_graphical_candidate_clients=0,published=False,
             source_code_sha256={str(path.relative_to(ROOT)):patcher.sha(path.read_bytes()) for path in
                (Path(patcher.__file__),Path(__file__),ROOT/'tools/verify_arena_empty_roster_navigation_native.py')})
 for name,value in (('combined-review.json',review),('native-composition.json',report)):
  target=FOLDER/name;data=(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf8')
  if target.exists():assert target.read_bytes()==data,'Immutable freeze differs: '+name
  else:
   with target.open('xb') as stream:stream.write(data)
 print(json.dumps(dict(passed=True,candidate_sha256=patcher.sha(candidate),candidate_bytes=len(candidate),
    combined_review_sha256=patcher.sha((FOLDER/'combined-review.json').read_bytes()),
    composition_sha256=patcher.sha((FOLDER/'native-composition.json').read_bytes()),native_auth_spans=len(SPANS),preservation=preservation)))
 return report
if __name__=='__main__':build()
