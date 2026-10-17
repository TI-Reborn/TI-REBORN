"""Freeze original captain Name only, wire geometry,600 sources and111 checks."""
from pathlib import Path
import ast,hashlib,json,re,sys
ROOT=Path(__file__).resolve().parents[1]
F=ROOT/'reports/gameplay-completion/legacy-status-20261011/runtime-native-lobby-original-names'
BASE=F.parent/'runtime-native-lobby-departure/isolated-runtime'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def static_scope(name):
    old=ast.parse((F/'deployed-source'/name).read_text(encoding='utf8'))
    new=ast.parse((F/'runtime'/name).read_text(encoding='utf8'))
    allowed={'list_packet','battle_list_packet'} if name.endswith('team_arena.py') else {'wager_rooms','wager_list_packet'}
    changed=[];calls=[]
    of={n.name:n for n in ast.walk(old) if isinstance(n,ast.FunctionDef)}
    nf={n.name:n for n in ast.walk(new) if isinstance(n,ast.FunctionDef)}
    assert of.keys()==nf.keys()
    for function in of:
        if ast.dump(of[function])!=ast.dump(nf[function]):
            assert function in allowed;changed.append(function)
            before=[ast.dump(n) for n in ast.walk(of[function]) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id in ('ArenaRoom','WagerRoomRecord','encode_room_list')]
            after=[ast.dump(n) for n in ast.walk(nf[function]) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id in ('ArenaRoom','WagerRoomRecord','encode_room_list')]
            assert before==after;calls.append(dict(function=function,wire_record_constructor_calls_identical=True,wire_call_count=len(before)))
    assert set(changed)==allowed
    for module in (old,new):
        for node in ast.walk(module):
            if isinstance(node,ast.FunctionDef) and node.name in allowed:node.body=[ast.Pass()]
    assert ast.dump(old)==ast.dump(new),'Changes outside four permitted Name formatters'
    return dict(changed_methods=sorted(changed),all_other_AST_identical=True,wire_calls=calls)

def main():
    candidate=json.loads((F/'candidate.json').read_text(encoding='utf8'))
    log=(F/'isolated-tests-final.log').read_text(encoding='utf8');assert re.search(r'Ran 111 tests.*?\bOK\b',log,re.S)
    native=json.loads((F/'native-tcp-sequence-proof.json').read_text(encoding='utf8'));assert native['passed'] and len(native['cases'])==24
    assert native['all_16_departure_TCP_streams_identical_to_deployed21ac_a26']
    changed=[];unchanged={}
    for source in BASE.rglob('*.py'):
        rel=source.relative_to(BASE);target=F/'isolated-runtime'/rel;assert target.exists()
        key=str(rel).replace('\\','/')
        if source.read_bytes()!=target.read_bytes():changed.append(key)
        else:unchanged[key]=sha(source)
    assert sorted(changed)==['server/team_arena.py','server/wager_arena.py']
    prior=json.loads((F.parent/'runtime-native-lobby-departure/validation-final.json').read_text(encoding='utf8'))
    qualified=prior['unchanged_runtime_sha256'];assert len(qualified)==600
    assert all(unchanged.get(name)==value for name,value in qualified.items())
    extras={name:value for name,value in unchanged.items() if name not in qualified}
    assert set(extras)=={'tests/test_native_lobby_departure_tcp.py'}
    scopes={}
    for name in changed:
        assert sha(F/'deployed-source'/name)==candidate['source_sha256'][name]==sha(BASE/name)
        assert sha(F/'runtime'/name)==candidate['candidate_sha256'][name]==sha(F/'isolated-runtime'/name)
        scopes[name]=static_scope(name)
    artifacts=['candidate.json','team_arena.diff','wager_arena.diff','isolated-tests-final.log','tcp-cases.json','native-tcp-sequence-proof.json']
    sources=['tools/build_native_lobby_original_names_candidate.py','tools/run_native_lobby_original_names_tests.py','tools/verify_original_names_departure_sequence_native.py','tools/freeze_native_lobby_original_names.py']
    report=dict(passed=True,tests_run=111,unchanged_runtime_source_count=600,unchanged_runtime_sha256=qualified,
                additional_inherited_QA_test_source_unchanged=extras,
                source_sha256=candidate['source_sha256'],candidate_sha256=candidate['candidate_sha256'],
                changed_runtime_sources=changed,code_scope=scopes,wire_count_capacity_soldiers_status_calls_identical=True,
                native_original_slot_sequences=24,all16_departure_TCP_streams_identical=True,
                inherited_111_proof_sha256=candidate['inherited_111_proof_sha256'],
                name_expectation_updates=candidate['name_expectation_updates'],
                QA_tests_are_separate_from_preserved_runtime=True,actual_deployed_baseline_readonly_verified=True,
                artifacts_sha256={name:sha(F/name) for name in artifacts},implementation_sources_sha256={name:sha(ROOT/name) for name in sources},
                scope='Only original Captain Name, remove status/count decorations in four ordinary/Wager Team/Wall list methods. Numeric slots/capacity/soldiers/status2, departure27, roster/admission, all other modes and transports untouched.',
                hosted_modified=False,hosted_player_data_opened=False,real_gui_candidate_validation=False,published=False)
    for name in sources:
        target=F/'source'/name;target.parent.mkdir(parents=True,exist_ok=True);raw=(ROOT/name).read_bytes()
        if target.exists():assert target.read_bytes()==raw
        else:target.write_bytes(raw)
    raw=(json.dumps(report,indent=2)+'\n').encode();target=F/'validation-final.json'
    if target.exists():assert target.read_bytes()==raw
    else:target.write_bytes(raw)
    print(json.dumps(dict(passed=True,report_sha256=sha(target),candidate_sha256=report['candidate_sha256'],unchanged_runtime_sources=600,tests=111,native_sequences=24)))
if __name__=='__main__':main()
