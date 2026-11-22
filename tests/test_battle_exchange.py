from contextlib import closing
from dataclasses import replace
import json,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from test_combat import item
from tio.battle_exchange import exchange,refresh
from tio.battle_loot import BattleLoot
from tio.combat import Combat
from tio.battle_state import BattleActor,BattleField
from tio.weapons import WeaponCatalog
from tio.owned_pets import OwnedPetStore
from tio.protocol.item_list import encode_item_list,decode_item_list
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.battle_exchange import BattleExchange,encode_exchange,decode_exchange
from tio.weight import project_base_weight,inventory_weight

ROOT=Path(__file__).resolve().parents[1]


class ExchangeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'state.db'
        raw=bytes.fromhex(json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())['packet_hex'])
        pet=decode_pet_info(raw,human_equipment=True)
        self.field=BattleField(8,8,[BattleActor(1,7,1,1,15,100,100),BattleActor(2,7,2,1,15,100,100),BattleActor(3,8,3,1,15,100,100)],step_cost=1)
        self.field.combat=self.c=Combat(self.field,WeaponCatalog())
        self.initial=[encode_item_list(1,(item(101,3,30),item(102,301))),encode_item_list(2,(item(201,3,5),item(202,208)))]
        store=OwnedPetStore(self.path)
        for i,bag in enumerate(self.initial,1):
            raw=encode_pet_info(replace(pet,fields={**pet.fields,'0x8c43eb':i,'0x8c44a6':i}))
            store.ensure('alice',raw,bag,human=True)
            self.c.register(i,bag,human=True,path=self.path,account='alice',pet_packet=project_base_weight(raw,True,bag))
        self.c.register(3,encode_item_list(3,(item(301,3,10),)),human=True)
        self.field.loot=self.loot=BattleLoot(self.c,())
        self.req=BattleExchange(1,2,((202,1),),((101,10),(102,1)))

    def saved(self):
        with closing(sqlite3.connect(self.path)) as db:
            return dict(db.execute('SELECT pet_id,inventory_packet FROM owned_pets WHERE account="alice"'))

    def open(self,req=None,generation=1):
        r=req or self.req
        return exchange(self.c,7,BattleExchange(r.actor_id,r.target_id),generation)

    def transfer(self,req=None,generation=1):return exchange(self.c,7,req or self.req,generation)

    def contents(self,i):return {v.instance_id:v for v in decode_item_list(self.c.inventories[i])[1]}

    def test_wire_native_order_and_strict_parser(self):
        raw=encode_exchange(self.req)
        self.assertEqual(raw.hex(),'6e010000000200000002000000650000000a000000660000000100000001000000ca00000001000000')
        self.assertEqual(decode_exchange(raw),self.req)
        for bad in (raw[:-1],raw+b'0',b'X'+raw[1:],encode_exchange(replace(self.req,target_id=1)),
                    encode_exchange(replace(self.req,withdrawals=((202,1),(202,1)))),
                    encode_exchange(replace(self.req,withdrawals=((101,1),))),
                    encode_exchange(replace(self.req,deposits=((101,0xffffffff),)))):
            with self.subTest(bad=bad),self.assertRaises(ValueError):decode_exchange(bad)

    def test_atomic_bidirectional_partial_stack_cost_and_durability(self):
        self.open();before=self.contents(1)[102];weight=sum(inventory_weight(p) for p in self.initial)
        replies=self.transfer()
        self.assertEqual(self.contents(1)[101].count,20)
        self.assertNotIn(102,self.contents(1));self.assertEqual(self.contents(2)[102],before)
        self.assertEqual(self.contents(2)[201].count,15);self.assertIn(202,self.contents(1))
        self.assertEqual(self.field.actor(1).action_points,14);self.assertEqual(self.field.actor(2).action_points,15)
        self.assertEqual(sum(inventory_weight(self.c.inventories[i]) for i in (1,2)),weight)
        self.assertEqual(self.saved(),{i:self.c.inventories[i] for i in (1,2)})
        self.assertEqual(sum(p[0]==0x30 for p in replies),2)
        self.assertEqual(sum(p[0]==0x4e for p in replies),3)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertGreater(db.execute('SELECT next_id FROM item_sequences').fetchone()[0],201)

    def test_open_cancel_and_reopen_have_no_cost(self):
        before=self.saved();self.open();self.open()
        self.assertEqual(self.saved(),before);self.assertEqual(self.field.actor(1).action_points,15)
        self.transfer();self.assertEqual(self.field.actor(1).action_points,14)

    def test_one_ap_suffices(self):
        self.field._actors[1]=replace(self.field.actor(1),action_points=1)
        self.open();self.transfer();self.assertEqual(self.field.actor(1).action_points,0)

    def test_no_open_and_duplicate_confirmation_cannot_move_or_charge_twice(self):
        with self.assertRaises(ValueError):self.transfer()
        self.open();self.transfer();state=(dict(self.c.inventories),self.field.actor(1),self.saved(),self.loot.next_id)
        with self.assertRaises(ValueError):self.transfer()
        self.assertEqual((dict(self.c.inventories),self.field.actor(1),self.saved(),self.loot.next_id),state)

    def test_stale_turn_or_inventory_or_position_rejected(self):
        for kind in ('turn','inventory','position'):
            with self.subTest(kind=kind):
                self.open();before=self.saved();actor=self.field.actor(2);bag=self.c.inventories[2]
                if kind=='inventory':self.c.inventories[2]=encode_item_list(2,())
                if kind=='position':self.field._actors[2]=replace(actor,x=2,y=2)
                with self.assertRaises(ValueError):self.transfer(generation=2 if kind=='turn' else 1)
                self.assertEqual(self.saved(),before);self.assertEqual(self.field.actor(1).action_points,15)
                self.c.inventories[2]=bag;self.field._actors[2]=actor

    def test_ownership_life_range_wall_human_and_ap(self):
        for changes in (dict(owner_id=8),dict(health=0),dict(x=5),dict(x=1,y=1)):
            old=self.field.actor(2);self.field._actors[2]=replace(old,**changes)
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.open()
            self.field._actors[2]=old
        self.field._actors[2]=replace(self.field.actor(2),x=2,y=2);self.field.blocked=frozenset({(2,1)})
        with self.assertRaises(ValueError):self.open()
        self.field.blocked=frozenset();self.c.human[2]=False
        with self.assertRaises(ValueError):self.open()
        self.c.human[2]=True;self.field._actors[1]=replace(self.field.actor(1),action_points=0)
        with self.assertRaises(ValueError):self.open()

    def test_equipped_unavailable_and_bad_quantities_leave_both_bags(self):
        for selection in (((101,31),),((101,0),),((999,1),)):
            self.open();before=self.saved()
            with self.assertRaises(ValueError):self.transfer(replace(self.req,deposits=selection))
            self.assertEqual(before,self.saved())
        bag=encode_item_list(1,(item(101,301,equipped=True),))
        self.c.inventories[1]=bag;self.open()
        with self.assertRaisesRegex(ValueError,'Сначала снимите'):self.transfer(replace(self.req,deposits=((101,1),)))

    def test_second_write_failure_rolls_back_both_and_memory(self):
        self.open();before=self.saved();memory=dict(self.c.inventories);next_id=self.loot.next_id
        original=self.c._persist_inventory
        def fail(identity,*args,**kwargs):
            if identity==2:raise ValueError('Injected second write failure')
            return original(identity,*args,**kwargs)
        with patch.object(self.c,'_persist_inventory',side_effect=fail),self.assertRaises(ValueError):self.transfer()
        self.assertEqual(before,self.saved());self.assertEqual(self.c.inventories,memory)
        self.assertEqual(self.loot.next_id,next_id);self.assertEqual(self.field.actor(1).action_points,15)

    def test_external_db_change_rolls_back_first_inventory(self):
        self.open()
        with closing(sqlite3.connect(self.path)) as db,db:db.execute('UPDATE owned_pets SET inventory_packet=? WHERE pet_id=2',(encode_item_list(2,()),))
        before=self.saved()
        with self.assertRaises(ValueError):self.transfer()
        self.assertEqual(before,self.saved());self.assertEqual(self.c.inventories[1],self.initial[0])

    def test_temporary_split_never_becomes_saved_or_merges_into_permanent(self):
        temporary=replace(item(0x60000100,3,20),unknown_words=(300,300,300))
        self.c.inventories[1]=encode_item_list(1,(*self.contents(1).values(),temporary));self.c.temporary_items.add(temporary.instance_id)
        r=BattleExchange(1,2,(),((temporary.instance_id,5),));self.open(r);self.transfer(r)
        self.assertEqual(self.saved(),{1:self.initial[0],2:self.initial[1]})
        self.assertEqual(self.contents(2)[201].count,5)
        acquired=next(i for i in self.contents(2).values() if i.instance_id in self.c.temporary_items)
        self.assertEqual(acquired.count,5);self.assertNotEqual(acquired.instance_id,temporary.instance_id)

    def test_marker_rental_upgrade_and_damage_are_preserved(self):
        special=replace(item(102,301),unknown_words=(97,180,300),unknown_bytes_02=bytes((3,0,1,1)),optional_u32=600,unknown_bytes_03=bytes((5,0,0)))
        bag=encode_item_list(1,(special,));self.c.inventories[1]=bag
        with closing(sqlite3.connect(self.path)) as db,db:db.execute('UPDATE owned_pets SET inventory_packet=? WHERE pet_id=1',(bag,))
        r=BattleExchange(1,2,(),((102,1),));self.open(r);self.transfer(r)
        self.assertEqual(self.contents(2)[102],special)

    def test_refresh_never_discloses_foreign_inventory(self):
        packets=refresh(self.c,7,(1,3,999))
        self.assertTrue(packets);self.assertTrue(all(int.from_bytes(p[1:5],'little')==1 for p in packets))

    def test_slot_overflow_and_id_exhaustion_are_atomic(self):
        self.loot.policy={**self.loot.policy,'inventory_slots':2}
        r=BattleExchange(1,2,(),((102,1),));self.open(r)
        with self.assertRaisesRegex(ValueError,'В инвентаре бойца недостаточно места'):self.transfer(r)
        self.assertEqual(self.saved(),{1:self.initial[0],2:self.initial[1]})
        self.loot.next_id=0x100000000;self.open()
        with self.assertRaises(ValueError):self.transfer()
        self.assertEqual(self.field.actor(1).action_points,15)


class SharedExchangeTests(unittest.TestCase):
    def test_shared_transport_routes_only_owned_inventories_and_invalidates_disconnect(self):
        from test_shared_team_arena import SharedTeamTests
        base=SharedTeamTests();base.setUp();self.addCleanup(base.doCleanups)
        base.add_selected(0,2);base.add_selected(1,2)
        for index in (0,1):base.send(index,b'\xba\3\1\1');base.send(index,b'\x2e')
        owners=[base.hub.identities[s] for s in base.sessions[:2]]
        battle=base.hub.battles[owners[0]];f=battle['field'];own=f.actor_ids(owners[0]);enemy=f.actor_ids(owners[1])[0]
        f.blocked=frozenset();f._actors[own[0]]=replace(f.actor(own[0]),x=5,y=5);f._actors[own[1]]=replace(f.actor(own[1]),x=6,y=5)
        base.send(0,b'\x36');base.send(1,b'\x36');base.hub.tick()
        for q in base.hub.queues.values():q.clear()
        r=BattleExchange(*own)
        replies=base.send(0,encode_exchange(r))
        self.assertEqual({int.from_bytes(p[1:5],'little') for p in replies if p[0]==0x30},set(own))
        self.assertFalse(any(p[0]==0x30 for p in base.hub.queues[owners[1]]))
        bad=base.send(1,encode_exchange(BattleExchange(enemy,own[0])))
        self.assertTrue(any(p[0]==0xf0 for p in bad))
        self.assertFalse(any(p[0]==0x30 and int.from_bytes(p[1:5],'little') in own for p in bad))
        self.assertIn(owners[0],f.combat.exchange_sessions)
        base.hub.disconnect(base.sessions[0]);self.assertNotIn(owners[0],f.combat.exchange_sessions)
