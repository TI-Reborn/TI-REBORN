"""Freeze125 checks, native BA02/BA06 and unchanged original25/27 TCP streams."""
from pathlib import Path
import ast,hashlib,json,re,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.verify_native_lobby_departure_sequence import sequence
F=ROOT/'reports/gameplay-completion/legacy-status-20261011/runtime-native-lobby-live-projection'
BASE=F.parent/'runtime-native-lobby-original-names'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    assert not (F/'validation-final.json').exists()
    candidate=json.loads((F/'candidate.json').read_text(encoding='utf8'))
    prior=json.loads((BASE/'validation-final.json').read_text(encoding='utf8'));assert prior['passed']
    assert sha(BASE/'validation-final.json')==candidate['inherited_111_proof_sha256']=='900f0bb127305420086cf7eaf111d4d5f27d84bddd8015c888c04db88e886382'
    log=(F/'isolated-tests-final.log').read_text(encoding='utf8');assert re.search(r'Ran 125 tests.*?\bOK\b',log,re.S)
    live=json.loads((F/'native-live-projection-proof.json').read_text(encoding='utf8'));assert live['passed'] and len(live['cases'])==16
    tcp=json.loads((F/'tcp-cases.json').read_text(encoding='utf8'));assert tcp['passed']
    old_tcp=json.loads((BASE/'tcp-cases.json').read_text(encoding='utf8'));assert old_tcp['cases']==tcp['cases'] and len(tcp['cases'])==16
    native=F.parent/'client-main-list-visibility/silver.dll';assert sha(native)=='e1d9435a8521881a6559dd3d724d9f5ca865a7aaa72d1707cf1669adaa3a4d80'
    cases=[sequence(native.read_bytes(),b,c) for c in tcp['cases'] if c['native_sequence_hex'] for b in (0x400000,0x10400000)];assert len(cases)==24
    departure=dict(passed=True,native_sha256=sha(native),cases=cases,all_16_prior_TCP_streams_byte_identical=True,original_25_27_consumers_executed=True,
                   verifier_sha256=sha(ROOT/'tools/verify_native_lobby_departure_sequence.py'),hosted_modified=False)
    (F/'native-departure-preservation-proof.json').write_bytes((json.dumps(departure,indent=2)+'\n').encode())
    changed=[];unchanged={}
    for source in (BASE/'isolated-runtime').rglob('*.py'):
        rel=source.relative_to(BASE/'isolated-runtime');key=rel.as_posix();target=F/'isolated-runtime'/rel;assert target.exists()
        if source.read_bytes()!=target.read_bytes():changed.append(key)
        else:unchanged[key]=sha(source)
    assert changed==['server/team_arena.py']
    baseline=prior['unchanged_runtime_sha256'];assert len(baseline)==600 and all(unchanged.get(name)==value for name,value in baseline.items())
    assert unchanged['server/wager_arena.py']==candidate['candidate_sha256']['server/wager_arena.py']==candidate['source_sha256']['server/wager_arena.py']
    for name in candidate['source_sha256']:
        assert sha(F/'qualified-source'/name)==candidate['source_sha256'][name]==sha(BASE/'runtime'/name)
        assert sha(F/'runtime'/name)==candidate['candidate_sha256'][name]==sha(F/'isolated-runtime'/name)
    old=ast.parse((F/'qualified-source/server/team_arena.py').read_text(encoding='utf8'))
    new=ast.parse((F/'runtime/server/team_arena.py').read_text(encoding='utf8'))
    oldf={n.name:n for n in ast.walk(old) if isinstance(n,ast.FunctionDef)};newf={n.name:n for n in ast.walk(new) if isinstance(n,ast.FunctionDef)}
    assert newf.keys()-oldf.keys()=={'remember_arena_listing'}
    allowed={'__init__','handle','tick','disconnect'};actual={name for name in oldf if ast.dump(oldf[name])!=ast.dump(newf[name])};assert actual==allowed
    # Prove every original tick statement and guard survives exactly; isolate
    # only the newly inserted BA projection statements inside its idle loop.
    oldloop=next(n for n in ast.walk(oldf['tick']) if isinstance(n,ast.For) and ast.unparse(n.target)=='(owner, s)')
    newloop=next(n for n in ast.walk(newf['tick']) if isinstance(n,ast.For) and ast.unparse(n.target)=='(owner, s)')
    assert len(oldloop.body)==3 and len(newloop.body)==6
    original_body=[newloop.body[0],newloop.body[1],newloop.body[-1]]
    assert [ast.dump(n) for n in original_body]==[ast.dump(n) for n in oldloop.body]
    newloop.body=original_body;assert ast.dump(newf['tick'])==ast.dump(oldf['tick'])
    original_methods={name:ast.dump(node) for name,node in oldf.items() if name not in allowed}
    assert all(ast.dump(newf[name])==value for name,value in original_methods.items())
    sources=['tools/build_native_lobby_live_projection_candidate.py','tools/run_native_lobby_live_projection_tests.py',
             'tools/test_native_lobby_live_projection.py','tools/verify_native_live_arena_list_consumers.py','tools/freeze_native_lobby_live_projection.py',
             'tools/verify_native_lobby_departure_sequence.py','tools/verify_legacy_lobbies_native.py','tools/verify_legacy_server_status_native.py']
    artifacts=['candidate.json','team_arena.py.diff','wager_arena.py.diff','isolated-tests-final.log','tcp-cases.json','live-tcp-cases.json',
               'native-live-projection-proof.json','native-departure-preservation-proof.json']
    report=dict(passed=True,tests_run=125,inherited_checks=111,new_live_projection_checks=14,
                source_sha256=candidate['source_sha256'],candidate_sha256=candidate['candidate_sha256'],
                inherited_111_proof_sha256=candidate['inherited_111_proof_sha256'],inherited_deployed_source_sha256=prior['source_sha256'],
                changed_vs_qualified_original_names_sources=changed,unchanged_runtime_source_count=600,unchanged_runtime_sha256=baseline,
                additional_unchanged_sources={name:pin for name,pin in unchanged.items() if name not in baseline},
                code_scope=dict(changed_original_methods=sorted(actual),new_methods=['remember_arena_listing'],all_other_original_methods_AST_identical=True,
                                all_original_tick_statements_and_offline_busy_city_C82C_guards_AST_identical=True,C82C_cache_still_bytes=True),
                native_BA02_BA06_complete_dispatch_sequences=16,native_original_25_27_sequences=24,all16_prior_departure_TCP_streams_identical=True,
                initial_BA01_deletions_tracked=True,retained_and_normal_disconnect_cache_cleanup_tested=True,hidden_window_not_opened_by_updates=True,
                native_DLL_sha256=sha(native),native_DLL_changed=False,wire_codecs_changed=False,Wager_candidate_bytes_unchanged=True,
                artifacts_sha256={name:sha(F/name) for name in artifacts},implementation_sources_sha256={name:sha(ROOT/name) for name in sources},
                scope='Changed-only BA02 live updates and original BA06 removals to idle city sessions; retain C82C guards/cache/auth initializers,25/27 departure, roster/admission, wire geometry and final original Names. Only Team runtime source differs from qualified629/c3.',
                hosted_modified=False,hosted_player_data_opened=False,published=False,real_GUI_candidate_validation=False)
    for name in sources:
        path=F/'source'/name;path.parent.mkdir(parents=True,exist_ok=True);assert not path.exists();path.write_bytes((ROOT/name).read_bytes())
    target=F/'validation-final.json';target.write_bytes((json.dumps(report,indent=2)+'\n').encode())
    print(json.dumps(dict(passed=True,qualification_sha256=sha(target),candidate_sha256=candidate['candidate_sha256'],tests=125,native_live_sequences=16,native_member_sequences=24)))
if __name__=='__main__':main()
