"""Offline QA control-flow tests: no sockets, credentials or hosting queries."""
from copy import deepcopy
import json
import hashlib
import struct
import unittest
from unittest.mock import patch

from tools import verify_hosted_world_completion as world
from tools import attest_hosted_world_completion as attestation


class Clock:
    def __init__(self):self.now=0
    def monotonic(self):return self.now
    def sleep(self,seconds):self.now+=seconds


class Network:
    def __init__(self):
        self.received={0:[],1:[]};self.peers={0:object(),1:object()};self.commands=[];self.reads=0
    def command(self,index,packet):self.commands.append((index,packet,self.reads))
    def ping(self,peer):pass


def owned(*,town=3,route=None,matches=(),audits=()):
    return dict(town=town,point=[town,20,30],route=route,matches=list(matches),encounters=[dict(match=m,level=1,dogs=2) for m in audits],health=[dict(id=1,current=50)])


class OrdinaryTravelTests(unittest.TestCase):
    def simulate(self,states,*,seconds=20,max_encounters=3):
        network=Network();clock=Clock();fixture=object();report={};calls=[]
        def read(actual_fixture,**kwargs):
            self.assertIs(actual_fixture,fixture);network.reads+=1;clock.now+=.1
            self.assertGreater(kwargs['timeout'],0);self.assertLessEqual(kwargs['timeout'],10)
            value=deepcopy(states[min(network.reads-1,len(states)-1)])
            if value['town']==4 and value['route'] is None and not value['matches']:
                network.received[0].append(b'\x1eactual-stop')
            calls.append(value)
            return dict(states=[value,owned()],centers={'4':[265,-397]},rates={},utc=clock.now)
        with patch.object(world,'world_state',side_effect=read),patch.object(world.time,'monotonic',clock.monotonic),patch.object(world.time,'sleep',clock.sleep),patch.object(world,'observe_town') as observe,patch.object(world,'progress'):
            result=world.travel(network,fixture,0,4,report,seconds=seconds,max_encounters=max_encounters)
        return result,network,report,clock,calls,observe

    def test_actual_arrival_without_encounter_uses_only_original_request(self):
        result,network,report,_,_,observe=self.simulate([owned(),owned(town=4)])
        self.assertTrue(result);self.assertEqual([c[1] for c in network.commands],[struct.pack('<Bii',0x1b,265,-397)])
        self.assertTrue(report['travel'][0]['native_1b_1e']);observe.assert_called_once()

    def test_one_encounter_resumes_only_after_checkpoint_gone_and_route_paused(self):
        result,network,report,_,_,observe=self.simulate([owned(),owned(matches=['road1'],audits=['road1']),owned(matches=['road1'],audits=['road1']),owned(route=[1,2,3,4,0,8],audits=['road1']),owned(audits=['road1']),owned(town=4,audits=['road1'])])
        self.assertTrue(result);self.assertEqual([c[1][:1] for c in network.commands],[b'\x1b',b'\x2a',b'\x2a',b'\x1b'])
        self.assertEqual(network.commands[-1][2],5)
        event=report['road_encounters'][0];self.assertEqual(event['match_ids'],['road1']);self.assertTrue(event['map_paused_after_escape']);self.assertEqual(event['native_escape_requests'],2)
        self.assertEqual(report['travel'][0]['requests'],2);observe.assert_called_once()

    def test_two_encounters_use_same_actual_destination_and_retain_both_audits(self):
        sequence=[owned(),owned(matches=['r1'],audits=['r1']),owned(audits=['r1']),owned(matches=['r2'],audits=['r1','r2']),owned(audits=['r1','r2']),owned(town=4,audits=['r1','r2'])]
        result,network,report,_,_,_=self.simulate(sequence)
        self.assertTrue(result);routes=[c[1] for c in network.commands if c[1][:1]==b'\x1b']
        self.assertEqual(routes,[world.travel_request((265,-397))]*3)
        self.assertEqual([r['match_ids'] for r in report['road_encounters']],[['r1'],['r2']])

    def test_three_encounters_escape_normally_then_stop_without_fourth_request(self):
        sequence=[owned()]
        for i in range(1,4):
            audits=['r'+str(j) for j in range(1,i+1)]
            sequence.extend([owned(matches=[audits[-1]],audits=audits),owned(audits=audits)])
        result,network,report,clock,_,observe=self.simulate(sequence)
        self.assertFalse(result);self.assertEqual(len([c for c in network.commands if c[1][:1]==b'\x1b']),3)
        self.assertEqual(len([c for c in network.commands if c[1]==b'\x2a\x01']),6)
        self.assertIn('retry bound',report['travel'][0]['limitation']);self.assertLess(clock.now,20);observe.assert_not_called()

    def test_stale_checkpoint_is_not_admin_reset_or_rerouted(self):
        result,network,report,clock,_,observe=self.simulate([owned(),owned(matches=['r1'],audits=['r1'])],seconds=2)
        self.assertFalse(result);self.assertEqual([c[1][:1] for c in network.commands],[b'\x1b',b'\x2a',b'\x2a'])
        self.assertFalse(report['road_encounters'][0]['map_paused_after_escape']);self.assertIn('cleanup',report['travel'][0]['limitation']);self.assertLess(clock.now,3);observe.assert_not_called()

    def test_deadline_includes_initial_reads_and_escapes_without_reset(self):
        result,network,report,clock,_,_=self.simulate([owned(),owned(matches=['r1'],audits=['r1']),owned(audits=['r1']),owned(route=[0,0,265,-397,0,300],audits=['r1'])],seconds=2)
        self.assertFalse(result);self.assertLess(clock.now,3);self.assertIn('real-time',report['travel'][0]['limitation'])
        self.assertEqual(report['travel'][0]['requests'],2)
        self.assertTrue(all(p==b'\x2a\x01' or p==world.travel_request((265,-397)) for _,p,_ in network.commands))

    def test_bounds_and_unowned_scene_fail_before_any_escape_or_network_request(self):
        for seconds,maximum in ((181,3),(0,3),(155,4),(155,True)):
            with patch.object(world,'world_state') as remote:
                with self.assertRaises(AssertionError):world.travel(Network(),object(),0,4,{},seconds=seconds,max_encounters=maximum)
                remote.assert_not_called()
        with self.assertRaises(AssertionError):self.simulate([owned(),owned(matches=['foreign-scene'])])

    def test_actual_four_arrivals_complete_even_when_an_encounter_occurred(self):
        report=dict(road_encounters=[dict(account=0,match_ids=['r1'])],travel=[dict(account=i,town=t,arrived=True,native_1b_1e=True) for i,t in ((0,4),(0,3),(1,18),(1,3))])
        self.assertEqual(world.travel_completion(report),dict(required_arrivals=4,actual_arrivals=4,missing_arrivals=[],completed=True))
        report['travel'][2]['arrived']=False
        self.assertEqual(world.travel_completion(report)['missing_arrivals'],[dict(account=1,town=18)])

    def test_packet_deadline_and_socket_timeout_are_restored_without_real_network(self):
        clock=Clock()
        class Raw:
            timeout=15
            def gettimeout(self):return self.timeout
            def settimeout(self,value):self.timeout=value
        class Peer:
            def __init__(self):self.sock=Raw()
            def receive(self):clock.now+=.6;return b'async'
        peer=Peer();original=peer.receive;network=Network();network.peers={0:peer}
        def pending():
            for _ in range(10):peer.receive()
        with patch.object(world.time,'monotonic',clock.monotonic):
            with self.assertRaises(AssertionError):world.bounded_native(network,1,pending)
        self.assertEqual(peer.receive,original);self.assertEqual(peer.sock.timeout,15);self.assertLess(clock.now,2)

    def test_travel_sql_read_has_a_real_subprocess_deadline_and_no_credentials(self):
        class Fixture:
            key='unused-local-key';host='unused.invalid'
            def ownership_payload(self):return dict(names=['ownedA','ownedB'],backup='ordinary-backup')
        from types import SimpleNamespace
        with patch.object(world.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='{}')) as run:
            self.assertEqual(world.world_state(Fixture(),timeout=2),{})
            self.assertEqual(run.call_args.kwargs['timeout'],2)
            self.assertNotIn('password',run.call_args.kwargs['input'])
            self.assertIn('mode=ro',run.call_args.args[0][-1])
            self.assertIn('PRAGMA query_only=ON',run.call_args.args[0][-1])


def receipt_state():
    return dict(encounters=[],ranks=[dict(account='owned',pet_id=1,points=0,debt=0)],health=[dict(id=1,current=50,maximum=50,immutable_profile_sha256='old-rank',escape_profile_sha256='only-hp-rank-masked',rank_projection_valid=True)],receipts={k:[] for k in world.PROTECTED_TABLES},protected={k:dict(rows=0,sha256='old') for k in world.PROTECTED_TABLES})


class OrdinaryEscapeProofTests(unittest.TestCase):
    def setUp(self):
        self.initial=dict(states=[receipt_state()]);self.final=deepcopy(self.initial)
        final=self.final['states'][0];final['encounters']=[dict(match='road',level=1,dogs=2)]
        final['ranks'][0]['points']=-20;final['health'][0]['immutable_profile_sha256']='native-minus20';final['health'][0]['current']=48
        final['receipts']['battle_rewards']=[dict(account='owned',match_id='road',result=0,credits=0,gross=0,rental_tax=0,calculation=json.dumps(dict(encounter=dict(kind='infected_dogs',level=1,dogs=2,credits=100),outcome=0,escaped=True)))]
        final['receipts']['rank_battle_audit']=[dict(account='owned',match_id='road',pet_id=1,before_points=0,earned=0,restored=0,penalty=20,after_points=-20)]
        final['receipts']['experience_battle_audit']=[dict(account='owned',match_id='road',pet_id=1,gain=0,xp_before=0,xp_after=0,level_before=1,level_after=1)]
        final['receipts']['player_battle_statistics']=[dict(account='owned',match_id='road',result=0,kills=0,deaths=0,damage_dealt=0,damage_received=2)]
        final['receipts']['soldier_ratings']=[dict(account='owned',pet_id=1,rating=0)]
        self.report=dict(road_encounters=[dict(account=0,match_ids=['road'],native_escape_requests=2,settled_health=[dict(id=1,current=48)])])

    def test_real_zero_reward_receipt_and_minus20_rank_are_exactly_authorized(self):
        proof=world.escape_receipts(self.initial,self.final,self.report)
        self.assertEqual(proof[0]['match_ids'],['road']);self.assertEqual(proof[0]['rank_penalties'],20)

    def test_known_diagnostic_legacy_allows_only_exact_precomputed_normalization(self):
        old=self.initial['states'][0]['health'][0];new=self.final['states'][0]['health'][0]
        old.update(diagnostic_legacy=True,normalized_initial_expected_escape_sha256='exact-existing-normalize',native_city_proficiency_vector=[35,0,75,285])
        new.update(diagnostic_legacy=False,escape_profile_sha256='exact-existing-normalize',native_city_proficiency_vector=[35,0,75,285])
        world.escape_receipts(self.initial,self.final,self.report)
        new['escape_profile_sha256']='arbitrary-skill-or-HP-cap-change'
        with self.assertRaises(AssertionError):world.escape_receipts(self.initial,self.final,self.report)
        new['escape_profile_sha256']='exact-existing-normalize';new['native_city_proficiency_vector'][0]=36
        with self.assertRaises(AssertionError):world.escape_receipts(self.initial,self.final,self.report)

    def test_nonlegacy_skill_snapshot_cannot_use_normalization_exception(self):
        old=self.initial['states'][0]['health'][0];new=self.final['states'][0]['health'][0]
        old.update(diagnostic_legacy=False,normalized_initial_expected_escape_sha256='different')
        new['escape_profile_sha256']='different'
        with self.assertRaises(AssertionError):world.escape_receipts(self.initial,self.final,self.report)

    def test_actual_proficiency_normalizer_changes_only_known_legacy_vector(self):
        from dataclasses import replace
        from tio.protocol.pet_info import decode_pet_info,encode_pet_info
        from tio.weapon_proficiency import ProficiencyRules,SAVED,BASE,CAPS,bits,number
        sample=json.loads((world.ROOT/'evidence/owned_pet_trial.json').read_text())['packet_hex']
        old=decode_pet_info(bytes.fromhex(sample),human_equipment=True)
        old=replace(old,fields={**old.fields,'0x8c4aef':1,**{key:bits(10) for key in (*SAVED,*BASE)},**{key:0 for key in CAPS}})
        normalized=decode_pet_info(ProficiencyRules().normalize(encode_pet_info(old),True),human_equipment=True)
        self.assertEqual([number(normalized.fields[key]) for key in SAVED],[35]*6+[0,35])
        self.assertEqual([normalized.fields[key] for key in CAPS],[75,285,75])
        self.assertEqual({k:v for k,v in old.fields.items() if k not in (*SAVED,*BASE,*CAPS)},{k:v for k,v in normalized.fields.items() if k not in (*SAVED,*BASE,*CAPS)})

    def test_receipt_missing_paid_unrelated_or_without_native_escape_is_rejected(self):
        cases=[]
        missing=deepcopy(self.final);missing['states'][0]['receipts']['battle_rewards']=[];cases.append((missing,self.report))
        paid=deepcopy(self.final);paid['states'][0]['receipts']['battle_rewards'][0]['credits']=1;cases.append((paid,self.report))
        extra=deepcopy(self.final);extra['states'][0]['receipts']['experience_battle_audit'][0]['match_id']='other';cases.append((extra,self.report))
        cases.append((self.final,dict(road_encounters=[])))
        for final,report in cases:
            with self.subTest(final=final):
                with self.assertRaises(AssertionError):world.escape_receipts(self.initial,final,report)

    def test_experience_offense_unknown_rank_and_native_profile_changes_rejected(self):
        for table,field,value in (('experience_battle_audit','gain',1),('rank_battle_audit','penalty',5),('rank_battle_audit','earned',1),('soldier_ratings','rating',1),('player_battle_statistics','damage_dealt',1)):
            final=deepcopy(self.final);final['states'][0]['receipts'][table][0][field]=value
            with self.subTest(table=table,field=field):
                with self.assertRaises(AssertionError):world.escape_receipts(self.initial,final,self.report)
        final=deepcopy(self.final);final['states'][0]['health'][0]['escape_profile_sha256']='different skill/gear/profile'
        with self.assertRaises(AssertionError):world.escape_receipts(self.initial,final,self.report)

    def test_existing_receipts_cannot_be_changed_or_erased_under_escape_exception(self):
        row=dict(account='owned',match_id='prior',result=0,credits=0)
        self.initial['states'][0]['receipts']['battle_rewards'].append(row)
        with self.assertRaises(AssertionError):world.escape_receipts(self.initial,self.final,self.report)
        self.final['states'][0]['receipts']['battle_rewards'].append({**row,'credits':1})
        with self.assertRaises(AssertionError):world.escape_receipts(self.initial,self.final,self.report)

    def test_empty_new_schema_key_does_not_hide_changed_nonempty_or_removed_foreign_rows(self):
        old=dict(existing=dict(rows=1,sha256='actual-old'))
        empty=dict(rows=0,sha256=hashlib.sha256(json.dumps([]).encode()).hexdigest())
        self.assertEqual(world.unchanged_foreign_rows(old,{**old,'new_empty':empty}),['new_empty'])
        for bad in ({},{'existing':dict(rows=1,sha256='changed')},{**old,'new':dict(rows=1,sha256='actual-new')},{**old,'new':dict(rows=0,sha256='not-empty')}):
            with self.assertRaises(AssertionError):world.unchanged_foreign_rows(old,bad)


class ReadOnlyPreservedJourneyAttestationTests(unittest.TestCase):
    def test_exact_backup_substitution_keeps_live_ownership_and_readonly_uri(self):
        class Fixture:
            def remote(self,source,payload):self.source=source;self.payload=payload;return {'readonly':True}
        fixture=Fixture();payload={'names':['ownedA','ownedB'],'backup':'original-owned-backup'}
        result=attestation.backup_read(world.WORLD_STATE,fixture,'/root/tio-before-gameplay-completion-gqmepid1/reservation.sqlite3',payload)
        self.assertEqual(result,{'readonly':True});self.assertEqual(fixture.payload,payload)
        self.assertTrue(fixture.source.startswith(attestation.OWNERSHIP))
        self.assertIn('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',fixture.source[:len(attestation.OWNERSHIP)])
        tail=fixture.source[len(attestation.OWNERSHIP):]
        self.assertIn('file:/root/tio-before-gameplay-completion-gqmepid1/reservation.sqlite3?mode=ro',tail)
        self.assertIn('PRAGMA query_only=ON',tail)

    def test_other_backup_or_unowned_source_is_rejected_before_ssh(self):
        from types import SimpleNamespace
        fixture=SimpleNamespace(remote=lambda *args: self.fail('No SSH allowed'))
        for source,path in ((world.WORLD_STATE,'/root/other.sqlite3'),('SELECT public','/root/tio-before-gameplay-completion-gqmepid1/reservation.sqlite3')):
            with self.assertRaises(AssertionError):attestation.backup_read(source,fixture,path,{})

    def test_unreviewed_native_report_cannot_trigger_remote_attestation(self):
        with patch.object(attestation,'status') as remote:
            with self.assertRaises(AssertionError):attestation.attest(object(),dict(passed=False,probe_sha256='forged'),'unused',{})
            remote.assert_not_called()


if __name__=='__main__':unittest.main()
