from wallet_fixture import fund_wallet
import json,sqlite3,struct,tempfile,unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from tio.world_encounters import EncounterService,POLICY,reward
from tio.locations import LocationStore,stop_packet,leave_town_packet
from tio.arena_service import ArenaService
from tio.wallets import WalletStore
from tio.owned_pets import OwnedPetStore
from tio.hiring import HireStore
from tio.city_catalogs import CityCatalogs
from tio.squad import SquadStore
from tio.protocol.battle_soldier import decode_battle_soldier

ROOT=Path(__file__).resolve().parents[1]


class FixedRandom:
    def random(self):return 0
    def randrange(self,n):return 7


class EncounterTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'state.db';self.now=[1000]
        self.locations=LocationStore(self.path,clock=lambda:self.now[0])
        template=bytes.fromhex(json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())['packet_hex'])
        hire=HireStore(self.path,CityCatalogs(ROOT/'config/city_catalogs.json'),template)
        for name in ('alice','bob'):
            fund_wallet(self.path, name, credits=10_000, gold=10_000);hire.hire(name,1)
            identity=OwnedPetStore(self.path).list(name)[0][0]
            SquadStore(self.path).assign(name,identity,1)
        self.arena=ArenaService(clock=lambda:self.now[0])
        self.service=EncounterService(self.path,self.arena,self.locations,clock=lambda:self.now[0],rng=FixedRandom())

    def travel(self,name='alice',character=42,target=(400,300)):
        return self.locations.travel(name,struct.pack('<Bii',0x1b,*target),character)

    def encounter(self):
        self.travel();self.now[0]+=20
        started=self.service.tick('alice',42,b'Alice');self.assertIsNotNone(started)
        return started[0]

    def test_distance_not_clicks_safe_zone_and_busy(self):
        self.travel()
        self.assertIsNone(self.service.tick('alice',42,b'Alice'))
        for _ in range(10):self.travel(target=(399,299))
        self.now[0]+=4
        self.assertIsNone(self.service.tick('alice',42,b'Alice'))
        self.now[0]+=20
        self.assertIsNone(self.service.tick('alice',42,b'Alice',busy=True))
        self.assertFalse(self.arena.rooms.snapshot())
        self.assertIsNotNone(self.service.tick('alice',42,b'Alice'))
        self.assertFalse(self.locations.travelling('alice'))
        self.assertIsNone(self.locations.current('alice'))

    def test_reroute_preserves_elapsed_distance(self):
        self.travel();self.now[0]+=5;self.travel(target=(350,200))
        with closing(sqlite3.connect(self.path)) as db:
            distance=db.execute('SELECT distance FROM world_encounter_state WHERE account=?',('alice',)).fetchone()[0]
        self.assertAlmostEqual(distance,30)
        self.now[0]+=15;self.assertIsNotNone(self.service.tick('alice',42,b'Alice'))

    def test_infected_npcs_native_dog_profile_and_regular_dogs_unchanged(self):
        room,scene=self.encounter();field=scene.field;combat=field.combat
        dogs=field.actor_ids(scene.bot_owner);self.assertEqual(len(dogs),2)
        self.assertEqual(set(combat.persistence),set(scene.actor_ids))
        self.assertEqual(combat.catalog.npc_defaults[103],65489)
        self.assertEqual(combat.catalog.equipped(b'',human=False,resource=5)[0].template_id,333)
        for dog in dogs:
            packet=scene.visibility.snapshot(dog)
            decoded=decode_battle_soldier(packet,human_equipment=False)
            self.assertEqual(decoded.fields['0x8c50fb'],103)
            self.assertEqual(decoded.fields['0x8c543f'],65489)
            self.assertEqual((field.actor(dog).health,field.actor(dog).action_points),(35,17))
            self.assertEqual(combat.defense(dog),0)
        self.assertEqual(room.request.mode,7)

    def test_victory_once_map_return_and_account_isolation(self):
        room,scene=self.encounter();position=self.locations.position('alice')
        before=WalletStore(self.path).ensure('alice').credits
        bob=OwnedPetStore(self.path).list('bob');bob_money=WalletStore(self.path).ensure('bob')
        for dog in scene.field.actor_ids(scene.bot_owner):
            scene.field._actors[dog]=replace(scene.field.actor(dog),health=0)
        replies=self.arena.finish_training(42,self.path,'alice');self.assertTrue(replies)
        self.assertEqual(WalletStore(self.path).ensure('alice').credits-before,75)
        self.assertFalse(self.arena.finish_training(42,self.path,'alice'))
        returned=self.arena.finish_results(42,b'\x2a\x01')
        self.assertIn(leave_town_packet(),returned);self.assertIn(stop_packet(42,*position),returned)
        self.assertEqual(returned,self.arena.finish_results(42,b'\x2a\x01'))
        self.assertEqual(OwnedPetStore(self.path).list('bob'),bob)
        self.assertEqual(WalletStore(self.path).ensure('bob'),bob_money)
        self.travel(target=(400,300));self.now[0]+=20
        self.assertIsNone(self.service.tick('alice',42,b'Alice'))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM world_encounter_audit').fetchone()[0],1)

    def test_actual_bite_uses_npc_weapon_and_spends_action_points(self):
        from tio.protocol.battle_attack import AttackRequest,encode_attack_request
        room,scene=self.encounter();field=scene.field
        dog=field.actor_ids(scene.bot_owner)[0];human=field.actor(scene.actor_ids[0])
        occupied={(a.x,a.y) for a in field._actors.values()}
        cell=next(p for p in ((human.x-1,human.y),(human.x+1,human.y),(human.x,human.y+1),(human.x,human.y-1)) if field.inside(*p) and p not in field.blocked and p not in occupied)
        field._actors[dog]=replace(field.actor(dog),x=cell[0],y=cell[1])
        self.arena.member_loaded(42,b'\x36')
        self.arena.begin_turn_packets(scene.bot_owner,field.actor_ids(scene.bot_owner),40)
        before=field.actor(dog).action_points
        packets=self.arena.attack(scene.bot_owner,encode_attack_request(AttackRequest(dog,human.x,human.y)),view=scene.visibility)
        self.assertTrue(packets)
        self.assertEqual(field.actor(dog).action_points,before-4)
        self.assertEqual(field.actor(dog).weapons[0].template_id,65489)

    def test_two_accounts_can_fight_independent_authoritative_encounters(self):
        room,scene=self.encounter()
        other=ArenaService(clock=lambda:self.now[0])
        service=EncounterService(self.path,other,self.locations,clock=lambda:self.now[0],rng=FixedRandom())
        self.travel('bob',77);self.now[0]+=20
        started=service.tick('bob',77,b'Bob');self.assertIsNotNone(started)
        self.assertIsNot(started[0][1].field,scene.field)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(set(r[0] for r in db.execute('SELECT account FROM world_encounter_audit')),{'alice','bob'})

    def test_checkpoint_restores_actual_dogs_map_return_and_reward(self):
        from server.battle_journal import PrivateJournal
        from tio.battle_snapshot import dumps,loads
        journal=PrivateJournal(self.arena,self.path,'alice',wall=lambda:self.now[0])
        room,scene=self.encounter()
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM battle_checkpoints').fetchone()[0],1)
        state,_=loads(dumps(self.arena),rebase=False)
        field=state._fields[room.room_id]
        self.assertEqual(field.encounter_report,scene.field.encounter_report)
        self.assertEqual(state._return_maps,self.arena._return_maps)
        self.assertEqual(field.combat.catalog.npc_defaults,{103:65489})

    def test_failed_scene_rolls_back_journey_claim_and_arena(self):
        from server.battle_journal import PrivateJournal
        PrivateJournal(self.arena,self.path,'alice')
        self.travel();self.now[0]+=20
        with patch('tools.encounter_scene.prepare_encounter',side_effect=ValueError('fixture fail')):
            with self.assertRaises(ValueError):self.service.tick('alice',42,b'Alice')
        self.assertTrue(self.locations.travelling('alice'))
        self.assertFalse(self.arena.rooms.snapshot())
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM world_encounter_audit').fetchone()[0],0)

    def test_loss_and_escape_no_credit_and_no_pvp_kill_points(self):
        room,scene=self.encounter();combat=scene.field.combat
        human=scene.actor_ids[0];dog=scene.field.actor_ids(scene.bot_owner)[0]
        combat.rank_kills=[(human,dog)]
        from tio.ranks import battle_report
        self.assertEqual(battle_report(combat,42)[human][0],0)
        self.assertEqual(reward(scene.field.encounter_report,0)[0],0)
        self.assertEqual(reward(scene.field.encounter_report,1,escaped=True)[0],0)
        for i in scene.actor_ids:scene.field._actors[i]=replace(scene.field.actor(i),health=0)
        before=WalletStore(self.path).ensure('alice').credits
        self.assertTrue(self.arena.finish_training(42,self.path,'alice'))
        self.assertEqual(WalletStore(self.path).ensure('alice').credits,before)

    def test_death_returns_to_each_nearest_city_and_persists_once(self):
        from tio.locations import center,nearest_city,town_packets
        with closing(sqlite3.connect(self.path)) as db:
            alive=db.execute('SELECT pet_id,pet_packet FROM owned_pets WHERE account=?',('alice',)).fetchall()
        for town,point in ((2,(-367,-485)),(3,(-230,-315)),(5,(190,100)),(8,(430,-225)),(9,(-77,-505))):
            with self.subTest(town=town):
                with closing(sqlite3.connect(self.path)) as db,db:
                    for identity,packet in alive:db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=?',(packet,'alice',identity))
                    self.locations._save(db,'alice',3,*center(3))
                    db.execute('DELETE FROM map_journeys WHERE account=?',('alice',))
                self.now[0]+=200
                room,scene=self.encounter();match=self.arena._match_ids[room.room_id]
                scene.field.return_position=point;self.arena._return_maps[42]=point
                with closing(sqlite3.connect(self.path)) as db,db:
                    db.execute('UPDATE world_encounter_audit SET x=?,y=? WHERE match_id=?',(*point,match))
                    self.locations._save(db,'alice',None,*point)
                self.assertEqual(nearest_city(*point),town)
                bob=self.locations.position('bob')
                for identity in scene.actor_ids:scene.field._actors[identity]=replace(scene.field.actor(identity),health=0)
                self.assertTrue(self.arena.finish_training(42,self.path,'alice'))
                self.assertEqual(self.locations.current('alice'),town)
                self.assertEqual(self.locations.position('alice'),center(town))
                self.assertFalse(self.locations.travelling('alice'))
                returned=self.arena.finish_results(42,b'\x2a\x01')
                self.assertIn(stop_packet(42,*center(town)),returned)
                for packet in town_packets(town):self.assertIn(packet,returned)
                self.assertEqual(returned,self.arena.finish_results(42,b'\x2a\x01'))
                self.assertEqual(self.locations.position('bob'),bob)
                from tio.battle_rewards import settle
                # A replay after subsequent travel must not move the account again.
                self.travel(target=(400,300));position=self.locations.position('alice')
                settle(self.path,'alice',match,0,encounter_report=scene.field.encounter_report,health={i:0 for i in scene.actor_ids})
                self.assertEqual(self.locations.position('alice'),position)
                self.assertTrue(self.locations.travelling('alice'))

    def test_draw_with_dead_squad_returns_to_city(self):
        room,scene=self.encounter()
        for identity in scene.field._actors:scene.field._actors[identity]=replace(scene.field.actor(identity),health=0)
        self.arena.finish_training(42,self.path,'alice')
        self.assertEqual(self.locations.current('alice'),3)

    def test_living_escape_stays_at_encounter_position(self):
        room,scene=self.encounter();position=self.locations.position('alice')
        self.arena.forfeit(42)
        self.assertIsNone(self.locations.current('alice'))
        self.assertEqual(self.locations.position('alice'),position)

    def test_dead_disconnect_returns_to_city_and_snapshot_retains_arrival(self):
        from tio.battle_snapshot import dumps,loads
        from tio.locations import center,town_packets
        room,scene=self.encounter()
        for identity in scene.actor_ids:scene.field._actors[identity]=replace(scene.field.actor(identity),health=0)
        self.arena.forfeit(42);self.arena.disconnect(42)
        self.assertEqual(self.locations.current('alice'),3)
        restored,_=loads(dumps(self.arena),rebase=False)
        replies=restored.finish_results(42,b'\x2a\x01')
        self.assertIn(stop_packet(42,*center(3)),replies)
        for packet in town_packets(3):self.assertIn(packet,replies)

    def test_defeat_location_rolls_back_with_settlement_failure(self):
        room,scene=self.encounter();point=self.locations.position('alice')
        for identity in scene.actor_ids:scene.field._actors[identity]=replace(scene.field.actor(identity),health=0)
        with patch('tio.clans.project_assets',side_effect=RuntimeError('fixture settlement failure')):
            with self.assertRaises(RuntimeError):self.arena.finish_training(42,self.path,'alice')
        self.assertIsNone(self.locations.current('alice'))
        self.assertEqual(self.locations.position('alice'),point)
        self.assertTrue(self.arena.finish_training(42,self.path,'alice'))
        self.assertEqual(self.locations.current('alice'),3)

    def test_client_resource_binding_existing_animation_and_uv(self):
        from xml.etree import ElementTree as ET
        folder=ROOT/'reports/dog-encounters/client'
        anim=ET.parse(folder/'animation.xml').getroot()
        self.assertEqual(anim.find("Race/r[@id='103']").get('Name'),'Dog')
        self.assertIsNotNone(anim.find('Dog'))
        items=ET.parse(folder/'items.xml').getroot()
        self.assertEqual(items.find("item[@id='65490']/value[@key='texture_1']").get('val'),'dog_infected.jpg')
        self.assertEqual(items.find("item[@id='65510']/value[@key='texture_1']").get('val'),'dog_alsatian.jpg')

if __name__=='__main__':unittest.main()
