"""Real SQLite clan/group authority; no hosted or graphical-client claim."""
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from pathlib import Path
import random
import sqlite3
import tempfile
import unittest

from tio.clans import ClansStore, ClanRejected
from tio.mine_claims import MineClaimsStore, frozen_claim
from tio.owned_pets import OwnedPetStore
from tio.protocol.pet_info import decode_pet_info, encode_pet_info
from tio.protocol.item_list import encode_item_list
from tio.territories import TerritoriesStore, TerritoryRejected, CONFIG, load_config
from tio.alliances import schema as alliance_schema


class TerritoriesTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.path = Path(folder.name)/'territories.sqlite3'
        policy, locations = load_config(CONFIG)
        self.now = float(locations[11]['first_start']+1)
        self.store = TerritoriesStore(self.path, clock=lambda: self.now, rng=random.Random(4))
        source = json.loads((Path(__file__).resolve().parents[1]/'evidence/owned_pet_trial.json').read_text())
        pet = decode_pet_info(bytes.fromhex(source['packet_hex']), human_equipment=True)
        pet = replace(pet, fields={**pet.fields, '0x8c4aef':4, '0x8c4a07':115, '0x8c4ab1':115})
        self.pets = OwnedPetStore(self.path)
        self.accounts = tuple(f'{prefix}{i}' for prefix in ('a', 'b', 'c') for i in range(4))
        for account in self.accounts:
            self.pets.ensure(account, encode_pet_info(pet), encode_item_list(1, ()), human=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE characters(account TEXT,slot INTEGER,name BLOB,name_key TEXT UNIQUE)')
            db.executemany('INSERT INTO characters VALUES (?,1,?,?)', [(a,a.encode(),a) for a in self.accounts])
        self.clans = ClansStore(self.path); self.cids = []
        for prefix in ('a', 'b', 'c'):
            leader = prefix+'0'; self.cids.append(self.clans.create(leader, ('Clan '+prefix.upper()).encode()))
            for i in range(1, 4):
                self.clans.invite(leader, (prefix+str(i)).encode()); self.clans.accept(prefix+str(i), 1)
        self.event = self.store.current_event(11)

    def group(self, prefix, town=11, count=4):
        group = self.store.create_group(prefix+'0', town)
        for i in range(1, count):
            self.store.join_group(prefix+str(i), group['id'])
        for i in range(count):
            self.store.ready(prefix+str(i), True)
        if count == 4:
            return self.store.start_group(prefix+'0')
        return self.store.group(group['id'])

    def tour(self, number=1):
        self.now = self.event['starts']+1800+(number-1)*2100+1
        self.store.sync()

    def pair(self):
        self.group('a'); self.group('b'); self.tour()
        pair = self.store.pair_ready(self.event['id'])
        self.assertIsNotNone(pair)
        self.store.bind_match('match-1', pair)
        return pair

    def results(self, pair, *, kill=False):
        values = {m['account']:dict(kills=0,deaths=0,damage_dealt=0,damage_taken=0)
                  for group in pair['groups'] for m in group['members']}
        if kill:
            one = pair['groups'][0]['members'][0]['account']
            two = pair['groups'][1]['members'][0]['account']
            values[one].update(kills=1,damage_dealt=115)
            values[two].update(deaths=1,damage_taken=115)
        return values

    def finish(self):
        self.now = self.event['ends']+1
        self.store.sync()
        return self.store.finalize(self.event['id'])

    def rows(self, table):
        with closing(sqlite3.connect(self.path)) as db:
            return tuple(db.execute('SELECT * FROM '+table+' ORDER BY 1,2'))

    def test_schedule_three_tours_and_fixed_pauses_survive_reload(self):
        for delta, phase, tour in ((0,'REGISTRATION',0),(1800,'TOUR1',1),
                (3600,'TOUR2_PAUSE',1),(3900,'TOUR2',2),(5700,'TOUR3_PAUSE',2),
                (6000,'TOUR3',3),(7800,'FINISHED',3)):
            self.now = self.event['starts']+delta
            reloaded = TerritoriesStore(self.path,clock=lambda:self.now)
            state = reloaded.current_event(11)
            self.assertEqual((state['phase'],state['tour']),(phase,tour))
        self.store.finalize(self.event['id'])
        self.assertEqual(self.store.current_event(11)['phase'],'WAIT_ASSAULT')
        self.assertEqual(self.store.current_event(11)['starts'],self.event['starts']+604800)

    def test_outpost_policy_and_checkpoint_bands(self):
        outpost=self.store.info(7)
        if outpost['enabled']:
            from tio.locations import center,LocationStore
            self.assertEqual(outpost['levels'],[4,20])
            self.assertEqual(outpost['max_upgrade'],3)
            self.assertEqual(center(7),(325,-400))
            LocationStore(self.path)
            with closing(sqlite3.connect(self.path)) as db,db:
                LocationStore._save(db,'a0',7,*center(7))
            current=self.store.current_event(7)
            self.store.finalize(current['id'])
            self.now=self.store.current_event(7)['starts']+1
            self.assertEqual(self.store.create_group('a0',7)['town'],7)
        else:
            with self.assertRaises(TerritoryRejected):self.store.create_group('a0',7)
        mining=json.loads((CONFIG.parent/'mining.json').read_text())
        for entry in mining['locations']:
            town=self.store.info(entry['id'])
            band=mining['bands'][entry['band']]
            self.assertEqual((town['levels'],town['capacity']),(band[:2],band[2]))

    def test_requires_four_ready_owned_living_selected_soldiers(self):
        group=self.group('a',count=3)
        with self.assertRaises(TerritoryRejected):self.store.start_group('a0')
        with self.assertRaises(TerritoryRejected):self.store.join_group('a3',group['id'],(2,))
        with self.assertRaises(TerritoryRejected):self.store.join_group('a3',group['id'],(1,1))
        with closing(sqlite3.connect(self.path)) as db,db:
            raw=db.execute("SELECT pet_packet FROM owned_pets WHERE account='a3'").fetchone()[0]
            pet=decode_pet_info(raw,human_equipment=True);pet.fields['0x8c4ab1']=0
            db.execute("UPDATE owned_pets SET pet_packet=? WHERE account='a3'",(encode_pet_info(pet),))
        with self.assertRaises(TerritoryRejected):self.store.join_group('a3',group['id'])
        self.assertEqual(len(self.store.group(group['id'])['members']),3)

    def test_enemy_cannot_join_and_account_cannot_change_group_in_event(self):
        a=self.store.create_group('a0',11)
        with self.assertRaises(TerritoryRejected):self.store.join_group('b0',a['id'])
        self.store.leave_group('a0')
        with self.assertRaises(TerritoryRejected):self.store.create_group('a0',11)
        b=self.store.create_group('a1',11)
        with self.assertRaises(TerritoryRejected):self.store.join_group('a0',b['id'])

    def test_unopposed_groups_wait_and_never_capture(self):
        self.group('a');self.tour()
        self.assertIsNone(self.store.pair_ready(self.event['id']))
        receipt=self.finish()
        self.assertFalse(receipt['captured']);self.assertIsNone(receipt['winner_clan'])
        self.assertEqual(receipt['influence'],{})

    def test_clan_and_alliance_cohort_locked_until_finalize(self):
        with closing(sqlite3.connect(self.path)) as db,db:
            alliance_schema(db)
            db.execute("INSERT INTO alliances(id,name,name_key,leading_clan,created) VALUES (1,?,?,?,?)",(b'AB','ab',self.cids[0],self.now))
            db.executemany('INSERT INTO alliance_members VALUES (?,1,?)',[(self.cids[0],self.now),(self.cids[1],self.now)])
        a=self.store.create_group('a0',11)
        self.store.join_group('b0',a['id'])
        self.assertEqual(a['clan_ids'],tuple(self.cids[:2]))
        self.assertEqual(len(self.rows('warfare_clan_locks')),2)
        with self.assertRaises(ClanRejected):self.clans.remove('a0',b'a1')
        with self.assertRaises(ClanRejected):self.clans.remove('b0',b'b1')
        self.finish()
        self.assertEqual(self.rows('warfare_clan_locks'),())
        self.clans.remove('b0',b'b1')

    def test_two_groups_same_alliance_cannot_pair(self):
        with closing(sqlite3.connect(self.path)) as db,db:
            alliance_schema(db)
            db.execute("INSERT INTO alliances(id,name,name_key,leading_clan,created) VALUES (1,?,?,?,?)",(b'AB','ab',self.cids[0],self.now))
            db.executemany('INSERT INTO alliance_members VALUES (?,1,?)',[(self.cids[0],self.now),(self.cids[1],self.now)])
        self.group('a');self.group('b');self.tour()
        self.assertIsNone(self.store.pair_ready(self.event['id']))

    def test_atomic_pair_reservation_concurrent_and_idempotent_binding(self):
        self.group('a');self.group('b');self.tour()
        with ThreadPoolExecutor(max_workers=2) as pool:
            found=list(pool.map(lambda _:self.store.pair_ready(self.event['id']),range(2)))
        self.assertEqual(sum(p is not None for p in found),1)
        pair=next(p for p in found if p is not None)
        first=self.store.bind_match('match-1',pair)
        self.assertEqual(self.store.bind_match('match-1',pair),first)
        with self.assertRaises(TerritoryRejected):self.store.leave_group(pair['groups'][0]['leader'])
        with self.assertRaises(TerritoryRejected):self.store.bind_match('fake',[100,101])

    def test_expired_unborn_pair_is_cancelled_but_bound_match_blocks_finalization(self):
        self.group('a');self.group('b');self.tour()
        pair=self.store.pair_ready(self.event['id'])
        self.now=self.event['starts']+3600
        self.store.sync()
        self.assertEqual(self.store.matches(self.event['id'])[0]['status'],'cancelled')
        with self.assertRaises(TerritoryRejected):self.store.bind_match('late',pair)
        for prefix in ('a','b'):
            for i in range(4):self.store.ready(prefix+str(i),True)
            self.store.start_group(prefix+'0')
        self.tour(2);pair=self.store.pair_ready(self.event['id']);self.store.bind_match('match-2',pair)
        self.now=self.event['ends']+1
        with self.assertRaises(TerritoryRejected):self.store.finalize(self.event['id'])
        self.store.settle_match(self.event['id'],'match-2',self.results(pair),flag_points=(344,280))
        self.assertTrue(self.store.finalize(self.event['id'])['captured'])

    def test_documented_344_280_anchor_half_ov_and_positive_event_influence(self):
        pair=self.pair();values=self.results(pair,kill=True)
        receipt=self.store.settle_match(self.event['id'],'match-1',values,(344,280))
        a=pair['groups'][0]['members'][0]
        b=pair['groups'][1]['members'][0]
        self.assertEqual(receipt['accounts'][a['account']]['ov_units'],11)
        self.assertEqual(receipt['accounts'][b['account']]['ov_units'],-1)
        self.assertEqual(receipt['clans'][str(a['clan_id'])],26)
        self.assertEqual(receipt['clans'][str(b['clan_id'])],5)
        result=self.finish()
        self.assertEqual(result['winner_clan'],a['clan_id'])
        self.assertEqual(result['influence'],{str(a['clan_id']):13,str(b['clan_id']):2})
        self.assertEqual(len([r for r in self.rows('clan_ledger') if r[3]=='assault_influence']),2)

    def test_empty_match_no_activity_does_not_capture_even_decisive(self):
        pair=self.pair()
        self.store.settle_match(self.event['id'],'match-1',self.results(pair),decisive=pair['groups'][0]['id'])
        result=self.finish()
        self.assertFalse(result['captured']);self.assertIsNone(result['winner_clan'])
        self.assertEqual(result['influence'],{})

    def test_replay_results_and_finalization_do_not_duplicate_scores_or_influence(self):
        pair=self.pair();values=self.results(pair,kill=True)
        result=self.store.settle_match(self.event['id'],'match-1',values,(344,280))
        scores=self.rows('warfare_scores')
        self.assertEqual(self.store.settle_match(self.event['id'],'match-1',values,(344,280)),result)
        self.assertEqual(self.rows('warfare_scores'),scores)
        self.assertEqual(self.finish(),self.store.finalize(self.event['id']))
        ledger=self.rows('clan_ledger')
        self.store.finalize(self.event['id'])
        self.assertEqual(self.rows('clan_ledger'),ledger)
        altered={k:dict(v) for k,v in values.items()};altered[next(iter(values))]['damage_dealt']+=1
        with self.assertRaises(TerritoryRejected):self.store.settle_match(self.event['id'],'match-1',altered,(344,280))

    def test_unbound_foreign_or_invalid_results_cannot_add_points(self):
        pair=self.pair();values=self.results(pair)
        for invalid in ('missing','foreign'):
            with self.assertRaises(TerritoryRejected):self.store.settle_match(self.event['id'],invalid,values,(1,0))
        values[next(iter(values))]['deaths']=2
        with self.assertRaises(TerritoryRejected):self.store.settle_match(self.event['id'],'match-1',values,(1,0))
        self.assertEqual(self.rows('warfare_scores'),())
        self.assertEqual(self.rows('warfare_match_receipts'),())

    def test_receipt_failure_rolls_back_scores_match_and_readiness(self):
        pair=self.pair();before=(self.rows('warfare_groups'),self.rows('warfare_matches'),self.rows('warfare_group_members'))
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("CREATE TRIGGER reject_receipt BEFORE INSERT ON warfare_match_receipts BEGIN SELECT RAISE(ABORT,'test'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.store.settle_match(self.event['id'],'match-1',self.results(pair,kill=True),(344,280))
        self.assertEqual(self.rows('warfare_scores'),())
        self.assertEqual(before,(self.rows('warfare_groups'),self.rows('warfare_matches'),self.rows('warfare_group_members')))

    def test_capture_failure_rolls_back_claim_history_award_and_locks(self):
        pair=self.pair();self.store.settle_match(self.event['id'],'match-1',self.results(pair,kill=True),(344,280))
        before=(self.rows('clans'),self.rows('clan_ledger'),self.rows('warfare_clan_locks'))
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("CREATE TRIGGER reject_event BEFORE INSERT ON warfare_event_receipts BEGIN SELECT RAISE(ABORT,'test'); END")
        self.now=self.event['ends']+1
        with self.assertRaises(sqlite3.IntegrityError):self.store.finalize(self.event['id'])
        self.assertEqual(self.rows('territory_claims'),());self.assertEqual(self.rows('territory_claim_history'),())
        self.assertEqual(before,(self.rows('clans'),self.rows('clan_ledger'),self.rows('warfare_clan_locks')))

    def test_claim_cas_preserves_an_intervening_owner_and_audits_result(self):
        pair=self.pair();self.store.settle_match(self.event['id'],'match-1',self.results(pair,kill=True),(344,280))
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('INSERT INTO territory_claims VALUES (?,?,0,1)',(11,self.cids[2]))
            db.execute('INSERT INTO territory_claim_history VALUES (11,1,?,0,?,?,?)',(self.cids[2],'test','fixture change',self.now))
        result=self.finish()
        self.assertFalse(result['captured']);self.assertEqual(result['reason'],'claim_changed')
        self.assertEqual(result['claim']['owner_clan'],self.cids[2])

    def test_checkpoint_capture_preserves_old_frozen_mine_lease_and_tax_history(self):
        self.now=self.store.locations[13]['first_start']+1
        # Establish a real pre-event owner through the existing idle-only API.
        previous=MineClaimsStore(self.path).admin_set_claim(13,self.cids[2],tax_percent=10,
            expected_revision=0,actor='test:operator',reason='isolated fixture')
        self.event=self.store.current_event(13)
        self.group('a',13);self.group('b',13);self.tour()
        pair=self.store.pair_ready(self.event['id']);self.store.bind_match('mine-assault',pair)
        self.store.settle_match(self.event['id'],'mine-assault',self.results(pair,kill=True),(344,280))
        result=self.finish()
        self.assertTrue(result['captured']);self.assertEqual(result['claim']['revision'],2)
        self.assertEqual(result['claim']['tax_percent'],0)
        with closing(sqlite3.connect(self.path)) as db:
            from tio.mine_claims import validate_frozen
            self.assertEqual(validate_frozen(db,previous),previous)
            self.assertEqual(frozen_claim(db,13),result['claim'])
            row=db.execute('SELECT actor FROM mine_claim_history WHERE location=13 AND revision=2').fetchone()
            self.assertEqual(row[0],'assault:'+self.event['id'])

    def test_backward_clock_does_not_reopen_registration_or_shortens_tour(self):
        self.group('a');self.tour(2)
        self.now=self.event['starts']+100
        self.assertEqual(self.store.current_event(11)['phase'],'TOUR2')
        with self.assertRaises(TerritoryRejected):self.store.join_group('b0',self.store.own_group('a0')['id'])

    def test_roster_lock_audit_failure_leaves_no_group_or_partial_cohort_lock(self):
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("CREATE TRIGGER reject_member BEFORE INSERT ON warfare_group_members BEGIN SELECT RAISE(ABORT,'test'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.store.create_group('a0',11)
        self.assertEqual(self.rows('warfare_groups'),())
        self.assertEqual(self.rows('warfare_clan_locks'),())

    def test_mixed_alliance_flag_credit_is_per_player_and_kills_stay_with_own_clan(self):
        with closing(sqlite3.connect(self.path)) as db,db:
            alliance_schema(db)
            db.execute("INSERT INTO alliances(id,name,name_key,leading_clan,created) VALUES (1,?,?,?,?)",(b'AB','ab',self.cids[0],self.now))
            db.executemany('INSERT INTO alliance_members VALUES (?,1,?)',[(self.cids[0],self.now),(self.cids[1],self.now)])
        group=self.store.create_group('a0',11)
        for account in ('a1','b0','b1'):self.store.join_group(account,group['id'])
        for account in ('a0','a1','b0','b1'):self.store.ready(account,True)
        self.store.start_group('a0');self.group('c');self.tour()
        pair=self.store.pair_ready(self.event['id']);self.store.bind_match('mixed',pair)
        side=next(i for i,g in enumerate(pair['groups']) if g['id']==group['id'])
        values=self.results(pair);victim=pair['groups'][1-side]['members'][0]['account']
        values['a0'].update(kills=1,damage_dealt=115);values[victim].update(deaths=1,damage_taken=115)
        flags=(344,280) if side==0 else (280,344)
        result=self.store.settle_match(self.event['id'],'mixed',values,flags)
        self.assertEqual(result['clans'][str(self.cids[0])],16)
        self.assertEqual(result['clans'][str(self.cids[1])],10)
        self.assertEqual(result['clans'][str(self.cids[2])],5)

    def test_tied_positive_score_retains_owner(self):
        # Freeze a current owner before this event is first materialized.
        with closing(sqlite3.connect(self.path)) as db,db:
            claim=dict(location=11,owner_clan=self.cids[1],tax_percent=3,revision=1)
            db.execute('INSERT INTO territory_claims VALUES (?,?,3,1)',(11,self.cids[1]))
            db.execute('INSERT INTO territory_claim_history VALUES (11,1,?,3,?,?,?)',(self.cids[1],'test','initial owner',self.now))
            db.execute('UPDATE warfare_events SET claim=? WHERE id=?',(json.dumps(claim),self.event['id']))
        pair=self.pair()
        self.store.settle_match(self.event['id'],'match-1',self.results(pair),(100,100))
        result=self.finish()
        self.assertEqual(result['winner_clan'],self.cids[1]);self.assertFalse(result['captured'])
        self.assertEqual(result['claim']['tax_percent'],3)

    def test_unowned_positive_tie_selects_stable_real_clan_id(self):
        pair=self.pair()
        self.store.settle_match(self.event['id'],'match-1',self.results(pair),(100,100))
        result=self.finish()
        self.assertTrue(result['captured'])
        self.assertEqual(result['winner_clan'],min(self.cids[:2]))

    def test_negative_event_net_score_does_not_mint_influence(self):
        pair=self.pair()
        self.store.settle_match(self.event['id'],'match-1',self.results(pair),(344,280))
        for account in ('a0','a1','a2','a3','b0','b1','b2','b3'):self.store.ready(account,True)
        self.store.start_group('a0');self.store.start_group('b0')
        second=self.store.pair_ready(self.event['id']);self.store.bind_match('match-2',second)
        values=self.results(second)
        loser=pair['groups'][1]['members'][0]['clan_id']
        loser_side=next(i for i,g in enumerate(second['groups']) if g['members'][0]['clan_id']==loser)
        for member in second['groups'][loser_side]['members']:values[member['account']].update(deaths=1,damage_taken=115)
        killer=second['groups'][1-loser_side]['members'][0]['account'];values[killer].update(kills=4,damage_dealt=460)
        self.store.settle_match(self.event['id'],'match-2',values,decisive=second['groups'][1-loser_side]['id'])
        result=self.finish()
        self.assertLess(result['scores'][str(loser)],0)
        self.assertNotIn(str(loser),result['influence'])

    def test_recovery_reads_frozen_roster_and_match_without_pairing_again(self):
        pair=self.pair()
        restored=TerritoriesStore(self.path,clock=lambda:self.now)
        match=restored.matches(self.event['id'])[0]
        self.assertEqual(match['status'],'running')
        self.assertEqual(set(m['account'] for g in match['roster'] for m in g['members']),set(self.results(pair)))
        self.assertIsNone(restored.pair_ready(self.event['id']))
        self.assertEqual(restored.own_group('a0')['status'],'running')
        result=restored.settle_match(self.event['id'],'match-1',self.results(pair),(344,280))
        self.assertEqual(result,self.store.settle_match(self.event['id'],'match-1',self.results(pair),(344,280)))

    def test_wounded_soldier_and_over_cap_equipped_weapon_rejected(self):
        with closing(sqlite3.connect(self.path)) as db,db:
            raw=db.execute("SELECT pet_packet FROM owned_pets WHERE account='a0'").fetchone()[0]
            pet=decode_pet_info(raw,human_equipment=True);pet.fields['0x8c4ab1']=114
            db.execute("UPDATE owned_pets SET pet_packet=? WHERE account='a0'",(encode_pet_info(pet),))
        with self.assertRaises(TerritoryRejected):self.store.create_group('a0',11)
        source=json.loads((Path(__file__).resolve().parents[1]/'evidence/owned_pet_trial.json').read_text())
        from tio.protocol.item_list import decode_item_list
        item=decode_item_list(bytes.fromhex(source['inventory_packet_hex']))[1][0]
        item=replace(item,unknown_u8_01=1,unknown_bytes_03=bytes((11,0,0)))
        with closing(sqlite3.connect(self.path)) as db,db:
            pet.fields['0x8c4ab1']=115
            db.execute("UPDATE owned_pets SET pet_packet=?,inventory_packet=? WHERE account='a0'",
                       (encode_pet_info(pet),encode_item_list(1,(item,))))
        with self.assertRaises(TerritoryRejected):self.store.create_group('a0',11)
        with closing(sqlite3.connect(self.path)) as db,db:
            item=replace(item,unknown_u8_01=0)
            db.execute("UPDATE owned_pets SET inventory_packet=? WHERE account='a0'",(encode_item_list(1,(item,)),))
        self.assertEqual(self.store.participant('a0',11)['max_upgrade'],10)
        self.store.create_group('a0',11)

    def test_disconnect_cancels_unborn_pair_but_preserves_running_frozen_roster(self):
        self.group('a');self.group('b');self.tour()
        pair=self.store.pair_ready(self.event['id'])
        account=pair['groups'][0]['members'][0]['account']
        group=self.store.disconnect(account)
        self.assertEqual(group['status'],'open')
        self.assertFalse(next(m['ready'] for m in group['members'] if m['account']==account))
        self.assertEqual(self.store.matches(self.event['id'])[0]['status'],'cancelled')
        for prefix in ('a','b'):
            for i in range(4):self.store.ready(prefix+str(i),True)
            self.store.start_group(prefix+'0')
        pair=self.store.pair_ready(self.event['id']);before=self.store.bind_match('running',pair)['roster']
        self.store.disconnect(account)
        self.assertEqual(next(m['roster'] for m in self.store.matches(self.event['id']) if m['match_id']=='running'),before)
        self.assertEqual(self.store.own_group(account)['status'],'running')

    def test_abort_replay_no_scores_and_settlement_conflict(self):
        pair=self.pair()
        first=self.store.abort_match(self.event['id'],'match-1','loading_timeout')
        self.assertEqual(first['status'],'aborted')
        self.assertEqual(self.store.abort_match(self.event['id'],'match-1','loading_timeout'),first)
        self.assertEqual(self.rows('warfare_scores'),())
        self.assertTrue(all(not m['ready'] for g in self.store.groups(11) for m in g['members']))
        with self.assertRaises(TerritoryRejected):self.store.abort_match(self.event['id'],'match-1','quarantine')
        with self.assertRaises(TerritoryRejected):self.store.settle_match(self.event['id'],'match-1',self.results(pair),(344,280))
        result=self.finish();self.assertFalse(result['captured']);self.assertEqual(result['influence'],{})

    def test_abort_receipt_failure_is_atomic(self):
        self.pair();before=(self.rows('warfare_groups'),self.rows('warfare_matches'))
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("CREATE TRIGGER reject_abort BEFORE INSERT ON warfare_match_receipts BEGIN SELECT RAISE(ABORT,'test'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.store.abort_match(self.event['id'],'match-1','server_fault')
        self.assertEqual(before,(self.rows('warfare_groups'),self.rows('warfare_matches')))

    def test_lost_eligibility_after_ready_does_not_throw_from_periodic_pairing(self):
        self.group('a');self.group('b');self.tour()
        with closing(sqlite3.connect(self.path)) as db,db:
            raw=db.execute("SELECT pet_packet FROM owned_pets WHERE account='a2'").fetchone()[0]
            pet=decode_pet_info(raw,human_equipment=True);pet.fields['0x8c4ab1']=114
            db.execute("UPDATE owned_pets SET pet_packet=? WHERE account='a2'",(encode_pet_info(pet),))
        self.assertIsNone(self.store.pair_ready(self.event['id']))
        group=self.store.own_group('a2')
        self.assertEqual(group['status'],'open')
        self.assertFalse(next(m['ready'] for m in group['members'] if m['account']=='a2'))
        self.assertEqual(self.store.matches(self.event['id']),())

    def test_fresh_levels_are_refrozen_when_same_band_player_readies_after_battle(self):
        pair=self.pair();self.store.settle_match(self.event['id'],'match-1',self.results(pair),(344,280))
        with closing(sqlite3.connect(self.path)) as db,db:
            raw=db.execute("SELECT pet_packet FROM owned_pets WHERE account='a2'").fetchone()[0]
            pet=decode_pet_info(raw,human_equipment=True);pet.fields['0x8c4aef']=5
            db.execute("UPDATE owned_pets SET pet_packet=? WHERE account='a2'",(encode_pet_info(pet),))
        for prefix in ('a','b'):
            for i in range(4):self.store.ready(prefix+str(i),True)
            self.store.start_group(prefix+'0')
        second=self.store.pair_ready(self.event['id'])
        member=next(m for g in second['groups'] for m in g['members'] if m['account']=='a2')
        self.assertEqual(member['levels'],(5,))
        self.store.bind_match('match-2',second)


if __name__ == '__main__':
    unittest.main()
