"""Read-only final attestation of an already completed native world journey.

This does not connect a game client, rerun travel, provision, heal or change a
save. Its narrow recovery case is the preserved four-arrival report rejected
because a known diagnostic legacy proficiency snapshot was canonicalized.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from tools.verify_hosted_arena_surroundings import OWNERSHIP,require
from tools.verify_hosted_economy_completion import SNAPSHOT,status
from tools.verify_hosted_stage7 import Stage7Fixture
from tools.verify_hosted_world_completion import WORLD_STATE,deployment_hashes,pin_world_release,world_state,travel_completion,escape_receipts,retained_assets,unchanged_foreign_rows


def backup_read(source,fixture,path,payload):
    require(source.startswith(OWNERSHIP),'Ownership-checked read-only snapshot required')
    require(path=='/root/tio-before-gameplay-completion-gqmepid1/reservation.sqlite3','Exact reviewed pre8 backup required')
    tail=source[len(OWNERSHIP):]
    require('file:/var/lib/tio-server/reservation.sqlite3?mode=ro' in tail,'Read-only snapshot URI missing')
    # Keep ownership verification against the live fixture and its original
    # provisioning backup; substitute only the observation database URI.
    code=OWNERSHIP+tail.replace('file:/var/lib/tio-server/reservation.sqlite3?mode=ro','file:'+path+'?mode=ro')
    return fixture.remote(code,payload)


def attest(fixture,failed,phase8,hashes):
    released=json.loads((ROOT/'reports/gameplay-completion/stage8-world/travel-probe-validation.json').read_text())
    require(failed.get('probe_sha256')==released['files']['tools/verify_hosted_world_completion.py'],'Original executed travel probe differs from released evidence')
    require(failed.get('passed') is False and failed.get('reason')=='Escape changed profile outside health/audited rank','Narrow preserved profile-normalization failure required')
    require(failed.get('world_client_release')==pin_world_release(phase8,hashes),'Executed native catalogue deployment chain differs')
    require(travel_completion(failed)['completed'] and failed.get('travel_completion',{}).get('actual_arrivals')==4,'All four actual native arrivals required')
    require(len(failed.get('outpost_battle_gate',()))==2 and all(r['native_ba03_rejected'] for r in failed['outpost_battle_gate']) and failed.get('detroit_battle_gate',{}).get('native_ba03_rejected'),'Actual natural LV battle gates missing')
    deployment=json.loads(Path(phase8).read_text());require(deployment.get('passed') is True and deployment.get('source_parity') is True,'Successful exact phase8 deployment required')
    require(failed['utc']>=deployment['timestamp_utc'],'Native journey predates deployment')
    sources=('tio/weapon_proficiency.py','tio/passive_stats.py','config/weapon_proficiency.json')
    normalization_sources={path:hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for path in sources}
    checked={**hashes,**normalization_sources};backup=deployment['backup']+'/reservation.sqlite3'
    after=status(fixture,checked)
    require(after['connections']==0 and not any(after['idle'].values()),'Owned native connections/checkpoints are not released')
    require(after['service']==deployment['service_state'] and after['integrity']=='ok','Game service/PID or integrity differs')
    payload={**fixture.ownership_payload(),'source_hashes':checked}
    before=backup_read(SNAPSHOT,fixture,backup,payload)
    initial=backup_read(WORLD_STATE,fixture,backup,fixture.ownership_payload());final=world_state(fixture)
    require(initial['proficiency_policy_sha256']==final['proficiency_policy_sha256']==normalization_sources['config/weapon_proficiency.json'],'Legacy normalization policy differs')
    escapes=escape_receipts(initial,final,failed)
    retained_assets(before,after,encounter=True,escapes=escapes)
    require(all(not r['matches'] and not r['route'] and r['town']==3 for r in final['states']),'Completed ordinary return did not retain Reservation')
    require([s['match_ids'] for s in escapes]==[sorted(match for event in failed['road_encounters'] if event['account']==i for match in event['match_ids']) for i in (0,1)],'Final receipts differ from actual retained encounter audits')
    require(all(len(s['match_ids'])==1 and s['rank_penalties']==20 for s in escapes),'This recorded journey must have exactly two main-actor zero-reward escapes')
    normalizations=[]
    for index,(a,b) in enumerate(zip(initial['states'],final['states'])):
        for old,new in zip(a['health'],b['health']):
            if not old['diagnostic_legacy']:continue
            require(old['id']==1 and new['id']==1,'Only the retained ordinary main legacy fighter can canonicalize')
            normalizations.append(dict(account=index,pet=old['id'],known_all10_zero_cap=True,initial_raw_profile_sha256=old['raw_profile_sha256'],normalized_initial_expected_pkt_sha256=old['normalized_initial_expected_pkt_sha256'],normalized_initial_expected_escape_sha256=old['normalized_initial_expected_escape_sha256'],actual_final_escape_sha256=new['escape_profile_sha256'],native_city_proficiency_before=old['native_city_proficiency_vector'],native_city_proficiency_after=new['native_city_proficiency_vector'],mask_only='current HP and four receipt-audited rank fields',no_skill_training_or_xp=True))
    require(len(normalizations)==2,'Exact two known diagnostic legacy main profiles required')
    return dict(source_sha256=hashes,normalization_source_sha256=normalization_sources,initial_baseline=dict(method='read-only exact pre8 stopped-service backup; phase8 deployment proved all135 previous tables unchanged before native QA',path=backup,owned_wallets=[s['wallet'] for s in before['states']],foreign_fingerprints=before['foreign']),normalizations=normalizations,ordinary_escape_proof=[dict(account=i,match_ids=s['match_ids'],rank_penalties=s['rank_penalties']) for i,s in enumerate(escapes)],initialized_empty_foreign_tables=unchanged_foreign_rows(before['foreign'],after['foreign']),initialized_empty_world_tables=unchanged_foreign_rows(initial['foreign'],final['foreign']),final_ordinary_locations=final['states'],cleanup=dict(connections=after['connections'],idle=after['idle'],integrity=after['integrity'],service=after['service']),wallets_inventory_ownership_preserved=True,foreign_state_preserved=True,service_unchanged=True,experience_and_levels_unchanged=True,awards_unchanged=True,payments_unchanged=True,no_new_native_actions=True,travel_incomplete=False)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture',type=Path,required=True);parser.add_argument('--failed',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--phase8',type=Path,default=ROOT/'reports/gameplay-completion/stage8-world/deployment.json')
    args=parser.parse_args(argv);require(not args.output.exists(),'Preserve existing evidence; fresh output required')
    failed=json.loads(args.failed.read_text());report={**failed,'passed':False,'attested_utc':datetime.now(timezone.utc).isoformat(),'preserved_failure':dict(path=str(args.failed),sha256=hashlib.sha256(args.failed.read_bytes()).hexdigest(),reason=failed.get('reason')),'attestation_tool_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'attestation_network_actions':0}
    try:
        hashes=deployment_hashes(ROOT/'reports/gameplay-completion',ROOT/'reports/gameplay-completion/stage7-clans/deployment.json',args.phase8)
        fixture=Stage7Fixture.load(args.fixture);require(fixture.prefix=='qsfc5dfe28' and fixture.host=='185.184.42.88','Exact retained ordinary pair required')
        report.update(attest(fixture,failed,args.phase8,hashes));report['passed']=True
        for key in ('error_type','error_locations','reason'):report.pop(key,None)
    except BaseException as error:
        import traceback
        report['error_type']=type(error).__name__;report['error_locations']=[dict(file=Path(f.filename).name,line=f.lineno) for f in traceback.extract_tb(error.__traceback__)]
        if isinstance(error,AssertionError):report['reason']=str(error)[:200]
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf8') as output:json.dump(report,output,ensure_ascii=False,indent=2)
    print(json.dumps(dict(passed=report['passed'],report=str(args.output),native_actions=0,credentials_printed=False)))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
