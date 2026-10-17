"""Prepare only the exact reviewed two-file update; read-only hosted inspection.

Does not stop, start, restart, upload, deploy or modify any hosted file/data.
The established apply transaction retains strict zero game connections,
fresh stopped database/code/config backups and code-only rollback.
"""
from pathlib import Path
import base64,hashlib,json,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools import deploy_gameplay_completion as established
from tools import deploy_stage4_economy as transaction
from tools.inspect_gameplay_completion import INSPECT
from tools.deploy_legacy_lobby_projection import PROTECTED_RUNTIME
F=ROOT/'reports/gameplay-completion/legacy-status-20261011/server-lobby-original-names-deployment'
QUALIFIED=F.parent/'runtime-native-lobby-original-names'
QUALIFICATION_SHA='900f0bb127305420086cf7eaf111d4d5f27d84bddd8015c888c04db88e886382'
PINS={'server/team_arena.py':('21ac51dfa56a8f868e222ab6b07725b03777dd4b63859d454c6cc37827f1c761','629285f4eef601f873a2f95451c65690f701d5f1fd0302e680469aaccc9cfe24'),
      'server/wager_arena.py':('a26bd6a66968492e12cbe9747662beb85a6741ca77d53a03ea68256a3401a99e','c3e66966c03ebd87900fa6d654d206c503778f7409c82db82a98cf2a1d9e7271')}
def sha(data):return hashlib.sha256(data).hexdigest()
def write(name,value):
    path=F/name;path.parent.mkdir(parents=True,exist_ok=True)
    raw=value if isinstance(value,bytes) else (json.dumps(value,indent=2)+'\n').encode('utf8')
    if path.exists():raise ValueError('Preserve existing prepared evidence: '+name)
    path.write_bytes(raw);return sha(raw)

def main():
    proof_raw=(QUALIFIED/'validation-final.json').read_bytes();assert sha(proof_raw)==QUALIFICATION_SHA
    proof=json.loads(proof_raw);assert proof['passed'] and proof['tests_run']==111 and proof['native_original_slot_sequences']==24
    assert proof['candidate_sha256']=={name:pins[1] for name,pins in PINS.items()}
    assert proof['source_sha256']=={name:pins[0] for name,pins in PINS.items()}
    assert len(proof['unchanged_runtime_sha256'])==600
    for name,pin in proof['unchanged_runtime_sha256'].items():
        assert sha((QUALIFIED/'isolated-runtime'/name).read_bytes())==pin,'Isolated qualified baseline differs: '+name
    for name,(before,after) in PINS.items():
        assert sha((QUALIFIED/'deployed-source'/name).read_bytes())==before
        assert sha((QUALIFIED/'runtime'/name).read_bytes())==after==sha((QUALIFIED/'isolated-runtime'/name).read_bytes())
    F.mkdir(parents=True,exist_ok=True);assert not (F/'deployment-manifest.json').exists()
    inspected=transaction.remote(INSPECT,dict(files=sorted(PINS)))
    assert inspected['integrity']=='ok'
    assert all(inspected['files'][name]['sha256']==pins[0] for name,pins in PINS.items())
    protected=transaction.remote(transaction.INSPECT,dict(files=list(PROTECTED_RUNTIME)))
    protected_sha={name:value['sha256'] for name,value in protected.items()}
    assert all(protected_sha[name]==proof['unchanged_runtime_sha256'][name] for name in PROTECTED_RUNTIME)
    for name,pin in protected_sha.items():inspected['guards']['/opt/tio-emulator/'+name]=pin
    write('remote-baseline.json',inspected)
    write('protected-runtime-inspection.json',dict(passed=True,source_sha256=protected_sha,remote_mutations=0))
    for name in PINS:write('runtime/'+name,(QUALIFIED/'runtime'/name).read_bytes())
    write('runtime-files.json',sorted(PINS))
    write('candidate-overrides.json',{name:'runtime/'+name for name in PINS})
    adapter=dict(passed=True,source_unchanged=True,source_sha256=proof['candidate_sha256'],
                 source_sha256_semantics='Qualified candidate bytes to apply, not previous deployed bytes',
                 previous_deployed_source_sha256=proof['source_sha256'],
                 qualified_proof=str((QUALIFIED/'validation-final.json').relative_to(ROOT)),qualified_proof_sha256=QUALIFICATION_SHA,
                 tests_run=111,native_original_slot_sequences=24,unchanged_runtime_source_count=600,
                 frozen_isolated_600_sources_checked=True,protected_hosted_runtime_sources_checked=len(PROTECTED_RUNTIME),
                 gameplay_TCP_streams_unchanged=True,hosted_mutations=0,local_player_data_uploaded=False)
    write('validation.json',adapter)
    # Established prepare re-inspects both hosted files and validates full bytes.
    result=subprocess.run([sys.executable,'-m','tools.deploy_gameplay_completion','prepare','--folder',str(F),'--files',*sorted(PINS)],cwd=ROOT,text=True,capture_output=True,check=True)
    print(result.stdout.strip())
    manifest=json.loads((F/'deployment-manifest.json').read_text(encoding='utf8'))
    assert set(manifest['files'])==set(PINS) and manifest['local_player_data_uploaded'] is False
    for name,(before,after) in PINS.items():
        entry=manifest['files'][name];assert (entry['before'],entry['after'])==(before,after)
        assert base64.b64decode(entry['content'],validate=True)==(QUALIFIED/'runtime'/name).read_bytes()
    program=established.program(manifest['files']);assert "if run('ss','-Htn','state','established'" in program
    assert 'Active game connections; deployment postponed' in program
    write('remote-apply-program.py',program.encode('utf8'))
    sources=['tools/prepare_native_lobby_original_names_deployment.py','tools/deploy_gameplay_completion.py','tools/deploy_stage4_economy.py','tools/inspect_gameplay_completion.py']
    pins={name:sha((ROOT/name).read_bytes()) for name in sources}
    for name in sources:write('source/'+name,(ROOT/name).read_bytes())
    artifacts=['validation.json','remote-baseline.json','protected-runtime-inspection.json','candidate-overrides.json','runtime-files.json','deployment-manifest.json','remote-apply-program.py']
    review=dict(passed=True,prepared=True,applied=False,source_sha256=proof['source_sha256'],candidate_sha256=proof['candidate_sha256'],
                qualified_proof_sha256=QUALIFICATION_SHA,artifacts_sha256={name:sha((F/name).read_bytes()) for name in artifacts},
                implementation_sources_sha256=pins,mutation_files=sorted(PINS),unchanged_runtime_source_count=600,
                protected_hosted_runtime_sources_checked=len(PROTECTED_RUNTIME),inspected_utc=inspected['observed_utc'],
                inspected_live_connections=inspected['game_connections'],preparation_does_not_require_clients_closed=True,
                apply_requires_strict_zero_connections=True,established_backup_fingerprint_and_code_only_rollback_preserved=True,
                remote_mutations=0,service_stop_or_restart_calls=0,local_player_data_uploaded=False)
    report_sha=write('preparation-review.json',review)
    print(json.dumps(dict(passed=True,prepared_files=sorted(PINS),review_sha256=report_sha,manifest_sha256=sha((F/'deployment-manifest.json').read_bytes()),remote_mutations=0,applied=False)))
if __name__=='__main__':main()
