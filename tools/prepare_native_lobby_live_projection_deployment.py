"""Prepare exact live BA projection and original Names; read-only remote inspection.

No stop/start/restart, upload/deploy or hosted writes. Established apply retains
strict zero connections, fresh stopped DB/code/config backups and code rollback.
"""
from pathlib import Path
import base64,hashlib,json,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools import deploy_gameplay_completion as established
from tools import deploy_stage4_economy as transaction
from tools.inspect_gameplay_completion import INSPECT
from tools.deploy_legacy_lobby_projection import PROTECTED_RUNTIME
F=ROOT/'reports/gameplay-completion/legacy-status-20261011/server-lobby-live-projection-deployment'
QUALIFIED=F.parent/'runtime-native-lobby-live-projection'
QUALIFICATION_SHA='524df4541fbe42abfdeb44714d0a93120a6f8aa49bf60603550fd8b8eb2afd31'
PINS={'server/team_arena.py':('21ac51dfa56a8f868e222ab6b07725b03777dd4b63859d454c6cc37827f1c761','e0446270b271fac7fad4656f8433c18a347d1f05cae3c23830988c0c2fef515f'),
      'server/wager_arena.py':('a26bd6a66968492e12cbe9747662beb85a6741ca77d53a03ea68256a3401a99e','c3e66966c03ebd87900fa6d654d206c503778f7409c82db82a98cf2a1d9e7271')}
def sha(raw):return hashlib.sha256(raw).hexdigest()
def write(name,value):
    target=F/name;target.parent.mkdir(parents=True,exist_ok=True)
    raw=value if isinstance(value,bytes) else (json.dumps(value,indent=2)+'\n').encode('utf8')
    assert not target.exists(),'Preserve prior preparation evidence: '+name
    target.write_bytes(raw);return sha(raw)
def main():
    proofraw=(QUALIFIED/'validation-final.json').read_bytes();assert sha(proofraw)==QUALIFICATION_SHA
    proof=json.loads(proofraw);assert proof['passed'] and proof['tests_run']==125
    assert proof['native_BA02_BA06_complete_dispatch_sequences']==16 and proof['native_original_25_27_sequences']==24
    assert proof['all16_prior_departure_TCP_streams_identical']
    assert proof['candidate_sha256']=={name:pin[1] for name,pin in PINS.items()}
    assert proof['inherited_deployed_source_sha256']=={name:pin[0] for name,pin in PINS.items()}
    assert len(proof['unchanged_runtime_sha256'])==600
    for name,pin in proof['unchanged_runtime_sha256'].items():assert sha((QUALIFIED/'isolated-runtime'/name).read_bytes())==pin,name
    for name,(before,after) in PINS.items():assert sha((QUALIFIED/'runtime'/name).read_bytes())==after==sha((QUALIFIED/'isolated-runtime'/name).read_bytes())
    assert not F.exists(),'Use a fresh preparation folder'
    inspected=transaction.remote(INSPECT,dict(files=sorted(PINS)));assert inspected['integrity']=='ok'
    assert all(inspected['files'][name]['sha256']==pin[0] for name,pin in PINS.items())
    protected=transaction.remote(transaction.INSPECT,dict(files=list(PROTECTED_RUNTIME)))
    protected_sha={name:value['sha256'] for name,value in protected.items()}
    assert all(protected_sha[name]==proof['unchanged_runtime_sha256'][name] for name in PROTECTED_RUNTIME)
    for name,pin in protected_sha.items():inspected['guards']['/opt/tio-emulator/'+name]=pin
    write('remote-baseline.json',inspected)
    write('protected-runtime-inspection.json',dict(passed=True,source_sha256=protected_sha,remote_mutations=0))
    for name in PINS:write('runtime/'+name,(QUALIFIED/'runtime'/name).read_bytes())
    write('runtime-files.json',sorted(PINS));write('candidate-overrides.json',{name:'runtime/'+name for name in PINS})
    adapter=dict(passed=True,source_unchanged=True,source_sha256=proof['candidate_sha256'],
        source_sha256_semantics='Exact qualified candidate bytes to apply',previous_deployed_source_sha256=proof['inherited_deployed_source_sha256'],
        qualified_original_names_source_sha256=proof['source_sha256'],qualified_proof=str((QUALIFIED/'validation-final.json').relative_to(ROOT)),qualified_proof_sha256=QUALIFICATION_SHA,
        tests_run=125,native_BA02_BA06_complete_dispatch_sequences=16,native_original_25_27_sequences=24,unchanged_runtime_source_count=600,
        frozen_isolated_600_sources_checked=True,protected_hosted_runtime_sources_checked=len(PROTECTED_RUNTIME),gameplay_departure_TCP_streams_unchanged=True,
        hosted_mutations=0,local_player_data_uploaded=False)
    write('validation.json',adapter)
    completed=subprocess.run([sys.executable,'-m','tools.deploy_gameplay_completion','prepare','--folder',str(F),'--files',*sorted(PINS)],cwd=ROOT,text=True,capture_output=True,check=True)
    print(completed.stdout.strip())
    manifest=json.loads((F/'deployment-manifest.json').read_text(encoding='utf8'));assert set(manifest['files'])==set(PINS) and not manifest['local_player_data_uploaded']
    for name,(before,after) in PINS.items():
        entry=manifest['files'][name];assert (entry['before'],entry['after'])==(before,after)
        assert base64.b64decode(entry['content'],validate=True)==(QUALIFIED/'runtime'/name).read_bytes()
    program=established.program(manifest['files']);assert "if run('ss','-Htn','state','established'" in program
    assert 'Active game connections; deployment postponed' in program
    write('remote-apply-program.py',program.encode('utf8'))
    sources=['tools/prepare_native_lobby_live_projection_deployment.py','tools/deploy_gameplay_completion.py','tools/deploy_stage4_economy.py',
             'tools/inspect_gameplay_completion.py','tools/deploy_legacy_lobby_projection.py']
    pins={name:sha((ROOT/name).read_bytes()) for name in sources}
    for name in sources:write('source/'+name,(ROOT/name).read_bytes())
    artifacts=['validation.json','remote-baseline.json','protected-runtime-inspection.json','runtime-files.json','candidate-overrides.json','deployment-manifest.json','remote-apply-program.py']
    review=dict(passed=True,prepared=True,applied=False,previous_deployed_source_sha256=proof['inherited_deployed_source_sha256'],
        qualified_original_names_source_sha256=proof['source_sha256'],candidate_sha256=proof['candidate_sha256'],qualified_proof_sha256=QUALIFICATION_SHA,
        artifacts_sha256={name:sha((F/name).read_bytes()) for name in artifacts},implementation_sources_sha256=pins,mutation_files=sorted(PINS),
        unchanged_runtime_source_count=600,protected_hosted_runtime_sources_checked=len(PROTECTED_RUNTIME),inspected_utc=inspected['observed_utc'],inspected_live_connections=inspected['game_connections'],
        apply_requires_strict_zero_connections=True,established_backup_fingerprint_code_rollback_preserved=True,
        remote_mutations=0,service_stop_restart_calls=0,native_DLL_changed=False,local_player_data_uploaded=False)
    pin=write('preparation-review.json',review)
    print(json.dumps(dict(passed=True,prepared=True,review_sha256=pin,manifest_sha256=sha((F/'deployment-manifest.json').read_bytes()),applied=False,remote_mutations=0)))
if __name__=='__main__':main()
