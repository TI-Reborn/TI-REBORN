from wallet_fixture import fund_wallet
import json,sqlite3,tempfile,unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from tio.wallets import WalletStore
from tio.crystal_market import CrystalMarket
from tio.mining import band
from tio.mine_map import generate

ROOT=Path(__file__).resolve().parents[1]


class MarketTests(unittest.TestCase):
    def test_atomic_sale_quote_clock_and_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'state.db';fund_wallet(path, 'a', credits=10_000, gold=10_000);now=[0]
            market=CrystalMarket(path,clock=lambda:now[0])
            with closing(sqlite3.connect(path)) as db,db:
                market.extract(db,'a','match',2500);market.extract(db,'a','match',2500)
            self.assertEqual(market.balance('a'),2500)
            with self.assertRaises(ValueError):market.sell('a',999)
            self.assertEqual(market.sell('a',1000),50_000)
            self.assertEqual(market.balance('a'),1500)
            self.assertEqual(market.rate(),50)
            with self.assertRaises(ValueError):market.sell('a',2000)
            self.assertEqual(market.balance('a'),1500)
            now[0]=1201
            self.assertEqual(market.rate(),50)
            self.assertEqual(WalletStore(path).ensure('a').spectra_crystals,1500)
            self.assertEqual(WalletStore(path).ensure('a').credits,60_000)

    def test_strict_bands_and_maps(self):
        for levels in ((1,),(3,),(4,7),(20,21)):
            with self.assertRaises(ValueError):band(levels)
        self.assertEqual(band((4,6))[2],1000)
        scenes=set()
        for seed in range(200):
            layout=generate(seed,role=1+seed%2);a=layout.arena;scenes.add(layout.resource)
            self.assertEqual((a.ground.width,a.ground.height,a.ground.unknown_u8),(60,60,5))
            self.assertEqual(len(a.bot_spawns),10)
            self.assertEqual(len(set(a.bot_spawns)),10)
            self.assertIn(len(layout.deposits),(2,3))
            if seed%2==0:self.assertTrue(set(a.player_spawns).issubset(layout.lift))
            self.assertFalse(set(a.bot_spawns)&set(a.player_spawns))
            self.assertFalse(set(layout.deposits)&a.blocked)
            # No mutant starts within nine walkable steps of any squad member.
            from collections import deque
            distances={p:0 for p in a.player_spawns};queue=deque(a.player_spawns)
            while queue:
                x,y=queue.popleft()
                if distances[x,y]>=9:continue
                for p in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
                    if p in distances or p in a.blocked or not (0<=p[0]<60 and 0<=p[1]<60):continue
                    distances[p]=distances[x,y]+1;queue.append(p)
            self.assertFalse(set(a.bot_spawns)&distances.keys())
        self.assertEqual(len(scenes),20)


class MiningTests(unittest.TestCase):
    def setUp(self):
        from tio.hiring import HireStore
        from tio.city_catalogs import CityCatalogs
        from tio.owned_pets import OwnedPetStore
        from tio.squad import SquadStore
        from tio.protocol.pet_info import decode_pet_info,encode_pet_info
        from tio.matchmaking import SurvivalQueue
        from tio.abilities import AbilityCatalog,AbilityLevel
        from tools.mining_scene import prepare_mining
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'test.db';fund_wallet(self.path, 'probe_user', credits=10_000, gold=10_000)
        self.market=CrystalMarket(self.path)
        template=bytes.fromhex(json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())['packet_hex'])
        HireStore(self.path,CityCatalogs(ROOT/'config/city_catalogs.json'),template).hire('probe_user',1)
        rows=OwnedPetStore(self.path).list('probe_user');self.identity=rows[0][0]
        pet=decode_pet_info(rows[0][1],human_equipment=True);pet.fields['0x8c4aef']=4
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('UPDATE owned_pets SET pet_packet=?',(encode_pet_info(pet),))
        SquadStore(self.path).assign('probe_user',self.identity,1)
        ticket=SurvivalQueue().join(42,OwnedPetStore(self.path).list('probe_user'))
        catalog=AbilityCatalog(AbilityLevel(r['id'],r['level'],r['fields']) for r in json.loads((ROOT/'config/abilities.json').read_text())['records'])
        self.scene=prepare_mining(self.path,'probe_user',ticket,catalog,seed=4)
        self.field=self.scene.field;self.mine=self.field.mining

    def test_native_mode_and_npc_stats(self):
        from tio.arena_service import ArenaService
        arena=ArenaService(clock=lambda:0)
        room,packets=arena.start_survival(42,b'Alice',self.scene)
        self.assertEqual(room.request.mode,7)
        self.assertEqual(len(self.field.actor_ids(self.scene.bot_owner)),10)
        self.assertEqual(self.field.actor(self.identity).sight_radius,5)
        for i in self.field.actor_ids(self.scene.bot_owner):
            a=self.field.actor(i)
            resource=self.scene.visibility.templates[i].fields['0x8c50fb']
            self.assertEqual((a.health,a.action_points),(150,15 if resource==102 else 20))
            self.assertEqual(self.field.combat.defense(i),128)
            self.assertEqual(self.scene.visibility.templates[i].fields['0x8c5731'],128)
            self.assertIn(resource,(100,102))
        self.assertFalse(arena.finish_training(42,self.path,'probe_user'))

    def test_hidden_enemies_registered_off_map_without_hp_or_movement_leak(self):
        from tio.protocol.battle_soldier import decode_battle_soldier
        view=self.scene.visibility
        mobs=self.field.actor_ids(self.scene.bot_owner)
        hidden=set(mobs)-view.visible
        records={s.soldier_id:s for p in self.scene.packets if p[0]==0x3b
                 for s in (decode_battle_soldier(p,human_equipment=True),)}
        self.assertEqual(set(records),set(self.field._actors))
        for identity in hidden:
            self.assertEqual(records[identity].position,(255,255))
            self.assertEqual(records[identity].fields['0x8c57bb'],1)
            self.field._actors[identity]=replace(self.field.actor(identity),x=55,y=55,health=37)
        self.assertFalse(any(p[0] in (0x3b,0x4e) for p in view.refresh()))

    def test_dead_mutant_retains_settled_pose_across_fog_cycles(self):
        view=self.scene.visibility;mob=self.field.actor_ids(self.scene.bot_owner)[0]
        self.field.blocked=frozenset();self.field.transparent_obstacles=frozenset()
        self.field._actors[self.identity]=replace(self.field.actor(self.identity),x=10,y=10,sight_radius=5)
        self.field._actors[mob]=replace(self.field.actor(mob),x=11,y=10)
        view.refresh()
        self.field._actors[mob]=replace(self.field.actor(mob),health=0)
        self.field._actors[self.identity]=replace(self.field.actor(self.identity),x=30,y=30)
        hidden_packets=view.refresh();self.assertNotIn(mob,view.visible)
        self.assertIn(mob,view.resident_corpses)
        self.assertFalse(any(p[0] in (0x43,0x3b,0x4e) and int.from_bytes(p[1:5],'little')==mob
                             for p in hidden_packets))
        for _ in range(3):
            self.field._actors[self.identity]=replace(self.field.actor(self.identity),x=10,y=10)
            packets=view.refresh()
            self.assertIn(mob,view.visible)
            self.assertFalse(any(p[0] in (0x3b,0x43,0x4e) and int.from_bytes(p[1:5],'little')==mob
                                 for p in packets))
            self.assertEqual(view.snapshot_packets(mob),())
            self.assertEqual(self.field.actor(mob).health,0)
            self.assertFalse(any(p[0]==0x4b for p in packets))
            self.field._actors[self.identity]=replace(self.field.actor(self.identity),x=30,y=30)
            view.refresh()

    def test_corpse_retention_is_private_to_each_observers_discovery(self):
        from tio.visibility import VisibilityView
        from tio.protocol.battle_soldier import decode_battle_soldier
        view=self.scene.visibility;mob=self.field.actor_ids(self.scene.bot_owner)[0]
        self.field.blocked=frozenset();self.field.transparent_obstacles=frozenset()
        self.field._actors[self.identity]=replace(self.field.actor(self.identity),x=10,y=10,sight_radius=5)
        self.field._actors[mob]=replace(self.field.actor(mob),x=11,y=10)
        view.refresh()
        self.field._actors[mob]=replace(self.field.actor(mob),health=0)
        view.refresh()
        self.field._actors[self.identity]=replace(self.field.actor(self.identity),x=30,y=30)
        view.refresh()
        fresh=VisibilityView(self.field,view.owner,view.templates)
        packets=fresh.refresh()
        masked=next(decode_battle_soldier(p,human_equipment=True) for p in packets
                    if p[0]==0x3b and int.from_bytes(p[1:5],'little')==mob)
        self.assertEqual(masked.position,(255,255))
        self.assertEqual(masked.fields['0x8c57bb'],0)
        self.assertNotIn(mob,fresh.resident_corpses)
        self.assertNotIn(mob,view.visible)
        self.assertIn(mob,view.resident_corpses)

    def test_native_owner_model_stays_alive_until_last_hidden_enemy_dies(self):
        from tio.protocol.battle_soldier import decode_battle_soldier
        view=self.scene.visibility;mobs=self.field.actor_ids(self.scene.bot_owner)
        self.field._actors[self.identity]=replace(self.field.actor(self.identity),x=1,y=1,sight_radius=1)
        for identity in mobs:self.field._actors[identity]=replace(self.field.actor(identity),x=55,y=55)
        models={}
        def apply(packets):
            for p in packets:
                if p[0]==0x3b:
                    s=decode_battle_soldier(p,human_equipment=True)
                    models[s.soldier_id]=(s.owner_id,s.fields['0x8c57bb'])
                elif p[0]==0x43:models.pop(int.from_bytes(p[1:5],'little'),None)
        apply(self.scene.packets);apply(view.refresh())
        for index,identity in enumerate(mobs):
            self.field._actors[identity]=replace(self.field.actor(identity),health=0)
            apply(view.refresh())
            self.assertEqual(any(owner==self.scene.bot_owner and hp>0 for owner,hp in models.values()),index<len(mobs)-1)

    def test_deposits_are_not_disclosed_before_squad_discovers_them(self):
        from tio.mining import Deposit
        self.field.blocked=frozenset()
        actor=self.field.actor(self.identity)
        self.field._actors[self.identity]=replace(actor,x=10,y=10,sight_radius=5)
        d=Deposit(1,(20,10),500,500)
        self.mine.deposits={d.position:d};self.mine.sent_deposits={}
        view=self.scene.visibility
        self.assertEqual(self.mine.packets(),())
        self.assertFalse(any(p[:2]==b'\xb0\x16' for p in view.refresh()))
        self.field._actors[self.identity]=replace(actor,x=15,y=10,sight_radius=5)
        self.field.blocked=frozenset({(18,10)})
        self.assertEqual(self.mine.packets(),()) # In radius, but behind a wall.
        self.field.blocked=frozenset()
        self.assertIn(d.packet(),view.refresh())
        self.assertNotIn(d.packet(),view.refresh())
        d.drill=object()
        self.field._actors[self.identity]=replace(actor,x=10,y=10,sight_radius=5)
        self.assertEqual(self.mine.advance(1),()) # No remote production leak.
        self.assertEqual(d.extracted,100)
        self.field._actors[self.identity]=replace(actor,x=15,y=10,sight_radius=5)
        self.assertIn(d.packet(),view.refresh()) # Current state on rediscovery.
        self.field._actors[self.identity]=replace(actor,x=20,y=10,health=0)
        d.left-=1
        self.assertEqual(self.mine.packets(),()) # A corpse cannot scout.

    def test_mob_damage_matches_manual_without_skill_or_upgrade_multipliers(self):
        from types import SimpleNamespace
        from tio.protocol.battle_attack import AttackRequest
        from tio.protocol.item_list import encode_item_list
        combat=self.field.combat
        attacker=self.field.actor_ids(self.scene.bot_owner)[0]
        self.field.blocked=frozenset()
        combat.inventories[self.identity]=encode_item_list(self.identity,())
        for endpoint,expected in ((0,57),(1,79)):
            self.field._actors[self.identity]=replace(self.field.actor(self.identity),x=10,y=10,health=1000,max_health=1000)
            self.field._actors[attacker]=replace(self.field.actor(attacker),x=11,y=10,action_points=20)
            combat.rng=SimpleNamespace(randrange=lambda n:0,randint=lambda a,b:b if endpoint else a)
            combat.attack(self.scene.bot_owner,AttackRequest(attacker,10,10))
            self.assertEqual(self.field.actor(self.identity).health,1000-expected)
            self.assertEqual(self.field.actor(attacker).action_points,15)

    def test_mob_death_has_no_rank_penalty_even_when_leaving_scene(self):
        from tio.ranks import battle_report
        from tio.battle_rewards import settle
        combat=self.field.combat;mob=self.field.actor_ids(self.scene.bot_owner)[0]
        self.field._actors[self.identity]=replace(self.field.actor(self.identity),health=0)
        combat.rank_kills=[(mob,self.identity)]
        report=battle_report(combat,42)
        self.assertEqual(report,{self.identity:(0,True,False)})
        for escape in (False,True):
            settle(self.path,'probe_user',f'mob-death-{escape}',0,rank_report=report,escaped=escape)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT penalty FROM rank_battle_audit').fetchall(),[(0,),(0,)])
        combat.rank_kills=[(self.identity,mob)]
        self.field._actors[self.identity]=replace(self.field.actor(self.identity),health=100)
        self.assertEqual(battle_report(combat,42),{self.identity:(0,False)})
        # Player-style opponents retain PvP death penalties, also in a mine.
        combat.resources[mob]=1
        combat.rank_kills=[(mob,self.identity)]
        self.field._actors[self.identity]=replace(self.field.actor(self.identity),health=0)
        report=battle_report(combat,42)
        self.assertEqual(report,{self.identity:(0,True)})
        settle(self.path,'probe_user','pvp-death',0,rank_report=report)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT penalty FROM rank_battle_audit WHERE match_id='pvp-death'").fetchone()[0],5)

    def test_drill_turns_weight_exit_and_exactly_once_settlement(self):
        from tio.arena_service import ArenaService
        from tio.protocol.item_list import decode_item_list,encode_item_list
        from tio.protocol.item_action import ItemAction
        from tio.weight import inventory_weight
        from tio.owned_pets import OwnedPetStore
        arena=ArenaService(clock=lambda:0);room,_=arena.start_survival(42,b'Alice',self.scene)
        combat=self.field.combat;a=self.field.actor(self.identity)
        drill=next(iter(self.field.loot.boxes.values()))[0]
        from tio.protocol.battle_position import BattlePositionRequest,encode_position_request
        from tio.protocol.battle_loot import LootTransfer,encode_loot_transfer
        arena.member_loaded(42,b'\x36');arena.begin_turn_packets(42,(a.actor_id,),40)
        x,y=next(iter(self.field.loot.boxes))
        self.field._actors[a.actor_id]=replace(a,x=x-1,y=y)
        arena.loot_action(42,encode_position_request(BattlePositionRequest(a.actor_id,x,y)))
        transfer=encode_loot_transfer(LootTransfer(a.actor_id,x,y,(),((drill.instance_id,0),)))
        arena.loot_action(42,transfer)
        with self.assertRaises(ValueError):arena.loot_action(42,transfer)
        self.assertEqual(inventory_weight(combat.inventories[a.actor_id]),100)
        d=next(iter(self.mine.deposits.values()))
        self.field._actors[a.actor_id]=replace(self.field.actor(a.actor_id),x=d.position[0],y=d.position[1])
        self.mine.install(42,ItemAction(a.actor_id,drill.instance_id,255))
        self.assertEqual(self.mine.advance(2),(d.packet(),))
        self.assertEqual(d.extracted,100)
        self.assertEqual(self.mine.advance(2),())
        self.mine.advance(3)
        with self.assertRaises(ValueError):self.mine.pickup(42,a.actor_id,*d.position,201)
        self.mine.pickup(42,a.actor_id,*d.position,150)
        self.assertEqual(inventory_weight(combat.inventories[a.actor_id]),250)
        with self.assertRaises(ValueError):self.mine.exit(42)
        x,y=next(iter(self.mine.layout.lift));self.field._actors[a.actor_id]=replace(self.field.actor(a.actor_id),x=x,y=y)
        self.assertEqual(self.mine.exit(42),150)
        self.assertTrue(arena.finish_training(42,self.path,'probe_user'))
        self.assertFalse(arena.finish_training(42,self.path,'probe_user'))
        self.assertEqual(self.market.balance('probe_user'),150)
        self.assertFalse(any(i.template_id==52 for _,_,inv in OwnedPetStore(self.path).list('probe_user') for i in decode_item_list(inv)[1]))

    def test_mined_drill_survives_death_pickup_reinstallation_and_exit(self):
        from tio.protocol.item_list import decode_item_list,encode_item_list
        from tio.protocol.battle_position import BattlePositionRequest
        from tio.protocol.battle_loot import LootTransfer
        from tio.protocol.item_action import ItemAction
        from tio.protocol.battle_attack import AttackRequest
        from tio.battle_state import BattleActor
        from test_combat import FixedRandom
        combat=self.field.combat;loot=self.field.loot;identity=self.identity
        crate=next(iter(loot.boxes));drill=loot.boxes[crate][0]
        self.field._actors[identity]=replace(self.field.actor(identity),x=crate[0]-1,y=crate[1],action_points=30)
        loot.open(42,BattlePositionRequest(identity,*crate),1)
        loot.transfer(42,LootTransfer(identity,*crate,(),((drill.instance_id,0),)),1)
        d=next(iter(self.mine.deposits.values()));x,y=d.position
        self.field.blocked=frozenset();self.field.transparent_obstacles=frozenset()
        self.field._actors[identity]=replace(self.field.actor(identity),x=x,y=y)
        self.mine.install(42,ItemAction(identity,drill.instance_id,255))
        self.mine.advance(1);self.mine.advance(2)
        self.mine.pickup(42,identity,x,y,137)
        self.field._actors[identity]=replace(self.field.actor(identity),health=1)
        attacker=self.field.actor_ids(self.scene.bot_owner)[0]
        self.field._actors[attacker]=replace(self.field.actor(attacker),x=x+1,y=y,action_points=20)
        combat.rng=FixedRandom()
        combat.attack(self.scene.bot_owner,AttackRequest(attacker,x,y))
        self.assertEqual(loot.boxes[x,y][0].count,137)
        self.assertEqual(self.field.actor(identity).health,0)
        survivor=9999
        self.field._actors[survivor]=BattleActor(survivor,42,x,y,30,100,100)
        self.field._turn_points[survivor]=30
        combat.register(survivor,encode_item_list(survivor,()),human=True,pet_packet=combat.proficiencies[identity])
        loot.open(42,BattlePositionRequest(survivor,x,y),1)
        loot.transfer(42,LootTransfer(survivor,x,y,(),((drill.instance_id,137),)),1)
        self.mine.install(42,ItemAction(survivor,drill.instance_id,255))
        self.assertEqual(d.carried,137)
        self.mine.advance(3)
        self.assertEqual(d.extracted,237)
        self.mine.pickup(42,survivor,x,y,237)
        exit_position=next(iter(self.mine.layout.lift))
        self.field._actors[survivor]=replace(self.field.actor(survivor),x=exit_position[0],y=exit_position[1])
        self.assertEqual(self.mine.exit(42),237)
        self.assertFalse(any(i.template_id==52 for i in decode_item_list(combat.persistent_inventory(combat.inventories[survivor]))[1]))

    def test_last_mutant_kill_keeps_turn_and_empty_drill(self):
        from tio.arena_service import ArenaService
        from tio.protocol.item_list import decode_item_list,encode_item_list
        from tio.protocol.battle_attack import AttackRequest,encode_attack_request
        from tio.protocol.battle_turn import encode_end_turn
        arena=ArenaService(clock=lambda:0);room,_=arena.start_survival(42,b'Alice',self.scene)
        arena.member_loaded(42,b'\x36');arena.begin_turn_packets(42,(self.identity,),40)
        self.field.blocked=frozenset()
        self.field._actors[self.identity]=replace(self.field.actor(self.identity),x=10,y=10)
        enemies=self.field.actor_ids(self.scene.bot_owner);target=enemies[0]
        for i in enemies:self.field._actors[i]=replace(self.field.actor(i),health=0)
        self.field._actors[target]=replace(self.field.actor(target),x=11,y=10,health=1)
        combat=self.field.combat;combat.npc_defense[target]=0
        class Hit:
            def randrange(self,n):return 0
            def randint(self,a,b):return a
        combat.rng=Hit()
        drill=next(iter(self.field.loot.boxes.values()))[0]
        combat.inventories[self.identity]=encode_item_list(self.identity,(drill,))
        arena.attack(42,encode_attack_request(AttackRequest(self.identity,11,10)))
        self.assertEqual(self.field.actor(target).health,0)
        self.assertEqual(decode_item_list(combat.inventories[self.identity])[1],(drill,))
        self.assertIn(room.room_id,arena._turns)
        self.assertFalse(arena.finish_training(42,self.path,'probe_user'))
        arena.end_turn(42,encode_end_turn(self.identity))
        self.assertEqual(arena.next_turn_owner(room.room_id),42)
        arena.begin_turn_packets(42,(self.identity,),40)
        self.assertEqual(self.mine.round,2)

    def test_mutants_use_melee_and_spend_action_points(self):
        from tio.arena_service import ArenaService
        from tio.training_bot import play_turn
        from tio.protocol.battle_turn import encode_end_turn
        arena=ArenaService(clock=lambda:0);room,_=arena.start_survival(42,b'Alice',self.scene)
        arena.member_loaded(42,b'\x36');arena.begin_turn_packets(42,(self.identity,),40)
        self.field.blocked=frozenset()
        self.field._actors[self.identity]=replace(self.field.actor(self.identity),x=10,y=10,health=1000,max_health=1000)
        enemies=self.field.actor_ids(self.scene.bot_owner);attacker=enemies[0]
        for i in enemies[1:]:self.field._actors[i]=replace(self.field.actor(i),health=0)
        self.field._actors[attacker]=replace(self.field.actor(attacker),x=11,y=10)
        arena.end_turn(42,encode_end_turn(self.identity))
        play_turn(arena,room.room_id,self.scene.bot_owner,view=self.scene.visibility)
        self.assertEqual(self.field.actor(attacker).action_points,0)
        self.assertLess(self.field.actor(self.identity).health,1000)
        self.assertEqual(arena.next_turn_owner(room.room_id),42)

    def test_multiple_mine_turns_do_not_spawn_or_revive_mutants(self):
        from tio.arena_service import ArenaService
        from tio.training_bot import play_turn
        from tio.protocol.battle_turn import encode_end_turn
        arena=ArenaService(clock=lambda:0);room,_=arena.start_survival(42,b'Alice',self.scene)
        arena.member_loaded(42,b'\x36')
        identities=set(self.field._actors)
        mobs=self.field.actor_ids(self.scene.bot_owner)
        dead=mobs[0]
        self.field._actors[dead]=replace(self.field.actor(dead),health=0)
        # Remain safely at the original entry throughout the patrol simulation.
        for _ in range(12):
            arena.begin_turn_packets(42,(self.identity,),40)
            before={i:self.field.actor(i) for i in mobs}
            arena.end_turn(42,encode_end_turn(self.identity))
            play_turn(arena,room.room_id,self.scene.bot_owner,view=self.scene.visibility)
            self.assertEqual(set(self.field._actors),identities)
            self.assertEqual(self.field.actor(dead),before[dead])
            for i in mobs[1:]:
                a=self.field.actor(i);old=before[i]
                self.assertEqual(a.health,old.health)
                self.assertNotIn((a.x,a.y),self.field.blocked)
                self.assertIn((a.x,a.y),self.field.bot_patrol_regions[i])
                self.assertLessEqual(abs(a.x-old.x)+abs(a.y-old.y),20-a.action_points)
                self.assertGreaterEqual(a.action_points,0)

    def test_fog_reappearance_preserves_mutant_identity_and_health(self):
        from tio.protocol.battle_soldier import decode_battle_soldier
        view=self.scene.visibility;mob=self.field.actor_ids(self.scene.bot_owner)[0]
        self.field.blocked=frozenset()
        self.field._actors[self.identity]=replace(self.field.actor(self.identity),x=10,y=10)
        self.field._actors[mob]=replace(self.field.actor(mob),x=12,y=10,health=37)
        view.refresh()
        self.assertIn(mob,view.visible)
        self.field._actors[self.identity]=replace(self.field.actor(self.identity),x=1,y=1)
        packets=view.refresh()
        self.assertNotIn(b'\x43'+mob.to_bytes(4,'little'),packets)
        hidden=decode_battle_soldier(next(p for p in packets if p[:5]==b'\x3b'+mob.to_bytes(4,'little')),human_equipment=True)
        self.assertEqual((hidden.fields['0x8c519b'],hidden.fields['0x8c51af'],hidden.fields['0x8c57bb']),(255,255,1))
        self.field._actors[self.identity]=replace(self.field.actor(self.identity),x=10,y=10)
        packet=next(p for p in view.refresh() if p[:5]==b'\x3b'+mob.to_bytes(4,'little'))
        restored=decode_battle_soldier(packet,human_equipment=True)
        self.assertEqual(restored.fields['0x8c57bb'],37)
        self.assertEqual((restored.fields['0x8c519b'],restored.fields['0x8c51af']),(12,10))
        self.assertEqual(len(self.field.actor_ids(self.scene.bot_owner)),10)

    def test_checkpoint_roles_gate_and_market_packets(self):
        from tio.arena_service import ArenaService
        from tio.locations import LocationStore,center
        from tio.mining_service import MiningService
        from tio.protocol.asset_count import decode_asset_count
        locations=LocationStore(self.path)
        arena=ArenaService(clock=lambda:0);service=MiningService(self.path,arena,locations)
        with self.assertRaises(ValueError):service.handle('probe_user',42,b'Alice',b'\xb0\x14\1')
        with closing(sqlite3.connect(self.path)) as db,db:
            locations._save(db,'probe_user',13,*center(13))
        self.assertEqual(service.handle('probe_user',42,b'Alice',b'\xb0\x2c')[1][0][:4],b'\xb0\x1a\1\0')
        with self.assertRaises(ValueError):service.handle('probe_user',42,b'Alice',b'\xb0\x14\3')
        for role in (1,2):
            (room,prepared),packets=service.handle('probe_user',42,b'Alice',bytes((0xb0,0x14,role)))
            self.assertEqual(prepared.field.mining.role,role)
            self.assertEqual(prepared.field.return_town,13)
            self.assertEqual(packets[-1],b'\x41')
            with self.assertRaises(ValueError):service.handle('probe_user',42,b'Alice',bytes((0xb0,0x14,role)))
            with self.assertRaises(ValueError):service.handle('probe_user',42,b'Alice',b'\xb0\x15'+bytes(10))
            arena.disconnect(42)
        with closing(sqlite3.connect(self.path)) as db,db:
            CrystalMarket.extract(db,'probe_user','market-test',1000)
        _,packets=service.handle('probe_user',42,b'Alice',b'\xb0\x1d\xe8\3\0\0')
        assets=decode_asset_count(packets[0])
        self.assertEqual(assets.spectra_crystals,0)
        self.assertEqual([p[:2] for p in packets[1:]],[b'\xb0\x20',b'\xb0\x1f'])

    def test_encrypted_checkpoint_entry_load_and_drill_transfer(self):
        import socket,threading
        from tools.loopback_exchange import LoopbackExchange
        from tio.locations import center
        from tio.protocol.transport import InitialCipher,InitialFrameReader,encode_initial_frame
        from tio.protocol.battle_position import BattlePositionRequest,encode_position_request
        from tio.protocol.battle_loot import LootTransfer,encode_loot_transfer,decode_container
        from tio.protocol.item_list import decode_item_list
        exchange=LoopbackExchange(Path(self.temp.name)/'events.json',database=self.path,
                                  open_town_probe=True,observation_seconds=0)
        exchange.probe_character_id=42;exchange.probe_character_name=b'Test'
        with closing(sqlite3.connect(self.path)) as db,db:
            exchange.locations._save(db,'probe_user',13,*center(13))
        server,client=socket.socketpair();client.settimeout(4)
        thread=threading.Thread(target=exchange.observe_game,args=(server,InitialFrameReader(InitialCipher('C2S')),InitialCipher('S2C')))
        thread.start()
        try:
            cipher=InitialCipher('C2S');reader=InitialFrameReader(InitialCipher('S2C'))
            def request(p,until):
                client.sendall(encode_initial_frame(p,cipher));packets=[]
                while not any(until(p) for p in packets):
                    chunk=client.recv(65535)
                    if not chunk:raise AssertionError(exchange.events)
                    packets.extend(reader.feed(chunk))
                return packets
            replies=request(b'\xb0\x2c',lambda p:p[:2]==b'\xb0\x2b')
            self.assertEqual(replies[0][:4],b'\xb0\x1a\1\0')
            replies=request(b'\xb0\x14\1',lambda p:p==b'\x41')
            self.assertTrue(any(p[0]==0x35 for p in replies))
            request(b'\x36',lambda p:p[0]==0x38)
            room=exchange.arena.rooms.snapshot()[0];field=exchange.arena._fields[room.room_id]
            self.assertEqual(len(field.living_actor_ids(field.mining.owner)),1)
            x,y=next(iter(field.loot.boxes));a=field.actor(self.identity)
            field._actors[self.identity]=replace(a,x=x-1,y=y)
            replies=request(encode_position_request(BattlePositionRequest(self.identity,x,y)),lambda p:p[0]==0x47)
            drill=decode_container(next(p for p in replies if p[0]==0x47))[3][0]
            replies=request(encode_loot_transfer(LootTransfer(self.identity,x,y,(),((drill.instance_id,0),))),lambda p:p[0]==0x30)
            items=decode_item_list(next(p for p in replies if p[0]==0x30))[1]
            self.assertTrue(any(i.template_id==52 and i.count==0 for i in items))
        finally:
            # Let the handler flush the remaining battle replies before closing
            # the client socket, which would reset the connection on Windows.
            client.shutdown(socket.SHUT_WR)
            thread.join(4)
            client.close()
            exchange.stop()
            server.close()
        self.assertFalse(thread.is_alive())
