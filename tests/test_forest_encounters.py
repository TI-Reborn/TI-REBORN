import json,sqlite3,unittest,xml.etree.ElementTree as ET
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
import test_world_encounters as fixtures
ROOT=fixtures.ROOT
from tio.protocol.item_list import ItemRecord,decode_item_list,encode_item_list
from tio.protocol.shop_sale import ShopSale
from tio.world_encounters import POLICY

class ForestTests(unittest.TestCase):
    setUp=fixtures.EncounterTests.setUp
    travel=fixtures.EncounterTests.travel
    encounter=fixtures.EncounterTests.encounter

    def victory(self):
        room,scene=self.encounter()
        for identity in scene.field.actor_ids(scene.bot_owner):scene.field._actors[identity]=replace(scene.field.actor(identity),health=0)
        self.arena.finish_training(42,self.path,'alice')
        return room,scene

    def materials(self,name='alice'):
        from tio.owned_pets import OwnedPetStore
        return [i for _,_,p in OwnedPetStore(self.path).list(name) for i in decode_item_list(p)[1] if i.template_id in (65487,65488)]

    def test_three_reachable_biomes_real_ground_brush_and_no_crates(self):
        from tools.encounter_scene import prepare_encounter
        from tio.matchmaking import SurvivalQueue
        from tio.owned_pets import OwnedPetStore
        from tio.abilities import AbilityCatalog,AbilityLevel
        source=json.loads((ROOT/'config/abilities.json').read_text())
        catalog=AbilityCatalog(AbilityLevel(r['id'],r['level'],r['fields']) for r in source['records'])
        ticket=SurvivalQueue().join(42,OwnedPetStore(self.path).list('alice'))
        for biome,brush in zip(POLICY['biomes'],(7,8,9)):
            for seed in (0,1,7,19):
                scene=prepare_encounter(self.path,'alice',ticket,catalog,seed=seed,biome=biome)
                ground=__import__('tio.protocol.battle_ground',fromlist=['decode_battle_ground']).decode_battle_ground(scene.packets[0])
                self.assertEqual(set(ground.first_layer),{brush});self.assertEqual(ground.unknown_u8,0)
                self.assertFalse(scene.field.loot.boxes)
                self.assertTrue(ground.entries)
                self.assertTrue(all(b'box' not in e.name and b'crate' not in e.name and b'house01' not in e.name for e in ground.entries))
                self.assertEqual(scene.field.scene_metadata['biome'],biome)

    def test_consecutive_biomes_differ_even_after_service_restart(self):
        from tio.world_encounters import EncounterService
        _,scene=self.victory();first=scene.field.scene_metadata['biome']
        self.arena.finish_results(42,b'\x2a\x01');self.now[0]+=200
        self.service=EncounterService(self.path,self.arena,self.locations,clock=lambda:self.now[0],rng=self.service.rng)
        _,second=self.encounter()
        self.assertNotEqual(second.field.scene_metadata['biome'],first)

    def test_victory_materials_once_and_shop_quantity_sale(self):
        from tio.owned_pets import OwnedPetStore
        from tio.wallets import WalletStore
        from tio.shop import ShopStore
        from tio.city_catalogs import CityCatalogs
        _,scene=self.victory();bag=self.materials()
        self.assertEqual({i.template_id:i.count for i in bag},{65487:2,65488:4})
        self.assertFalse(self.materials('bob'));self.assertFalse(self.arena.finish_training(42,self.path,'alice'))
        self.arena.finish_results(42,b'\x2a\x01');self.arena.finish_results(42,b'\x2a\x01')
        self.assertEqual(self.materials(),bag)
        owner=OwnedPetStore(self.path).list('alice')[0][0];shop=ShopStore(self.path,CityCatalogs(ROOT/'config/city_catalogs.json'))
        hide=next(i for i in bag if i.template_id==65487);before=WalletStore(self.path).ensure('alice').credits
        request=ShopSale(owner,hide.instance_id,1)
        self.assertEqual(shop.sell('alice',request,quote=True),30)
        self.assertEqual(WalletStore(self.path).ensure('alice').credits,before)
        shop.sell('alice',request)
        self.assertEqual(WalletStore(self.path).ensure('alice').credits,before+30)
        self.assertEqual(next(i for i in self.materials() if i.template_id==65487).count,1)

    def test_full_bag_fallback_to_warehouse_without_losing_loot(self):
        from tio.owned_pets import OwnedPetStore
        from tio.inventory_capacity import INVENTORY_SLOTS
        owner,_,raw=OwnedPetStore(self.path).list('alice')[0];_,items,flag=decode_item_list(raw)
        extra=tuple(ItemRecord(1000+i,10,b'\0\0',1,0,0,(1,1,1),b'\0'*4,None,b'\0'*3) for i in range(INVENTORY_SLOTS-len(items)))
        with closing(sqlite3.connect(self.path)) as db,db:db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=?',(encode_item_list(owner,(*items,*extra),flag),'alice',owner))
        self.victory()
        from tio.warehouse import WarehouseStore
        self.assertEqual({i.template_id:i.count for i in WarehouseStore(self.path).items('alice')},{65487:2,65488:4})

    def test_full_bag_award_merges_separate_auction_delivery_stacks_without_duplicates(self):
        from tio.inventory_capacity import INVENTORY_SLOTS
        from tio.owned_pets import OwnedPetStore
        from tio.warehouse import WarehouseStore
        from tio.battle_rewards import settle
        owner,_,raw=OwnedPetStore(self.path).list('alice')[0];_,items,flag=decode_item_list(raw)
        extra=tuple(ItemRecord(1000+i,10,b'\0\0',1,0,0,(1,1,1),b'\0'*4,None,b'\0'*3) for i in range(INVENTORY_SLOTS-len(items)))
        WarehouseStore(self.path)
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=?',(encode_item_list(owner,(*items,*extra),flag),'alice',owner))
            for identity,count in ((2000,2),(2001,3)):
                material=ItemRecord(identity,65487,b'\0\0',count,0,0,(0,0,0),b'\0'*4,None,b'\0'*3)
                db.execute('INSERT INTO warehouse_items VALUES (?,?,?)',('alice',identity,encode_item_list(0,(material,))))
        settle(self.path,'alice','auction-delivery',1,encounter_report=dict(kind='infected_dogs',level=1,dogs=2,credits=75,loot_version=1))
        saved=WarehouseStore(self.path).items('alice')
        self.assertEqual({i.template_id:i.count for i in saved},{65487:7,65488:4});self.assertEqual(len(saved),2)

    def test_loot_shop_and_shared_player_auction_preserve_ownership(self):
        from tio.owned_pets import OwnedPetStore
        from tio.warehouse import WarehouseStore
        from tio.player_auction import AuctionStore
        from test_player_auction import create_packet
        self.victory();hide=next(i for i in self.materials() if i.template_id==65487)
        owner=OwnedPetStore(self.path).list('alice')[0][0];warehouse=WarehouseStore(self.path,capacity=3000)
        warehouse.exchange('alice',owner,deposits=((hide.instance_id,hide.count),))
        auction=AuctionStore(self.path,pledge_percent=5)
        lot=auction.create('alice','Alice',create_packet(instance=hide.instance_id,count=1,price=100,step=10,buyout=200),session='forest-test',now=100)
        auction.bid('bob','Bob',lot,None,None,buyout=True,now=101)
        self.assertEqual({i.template_id:i.count for i in warehouse.items('bob')},{65487:1})
        self.assertEqual(warehouse.items('alice')[0].count,1)

    def test_loss_and_escape_never_award_materials(self):
        room,scene=self.encounter()
        for identity in scene.actor_ids:scene.field._actors[identity]=replace(scene.field.actor(identity),health=0)
        self.arena.finish_training(42,self.path,'alice');self.assertFalse(self.materials())
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM encounter_loot_awards').fetchone()[0],0)

    def test_award_failure_rolls_back_money_and_materials(self):
        from tio.battle_rewards import settle
        from tio.wallets import WalletStore
        before=WalletStore(self.path).ensure('alice').credits
        report=dict(kind='infected_dogs',level=1,dogs=2,credits=75,loot_version=1)
        with patch('tio.encounter_loot.encode_item_list',side_effect=RuntimeError('fixture codec failure')):
            with self.assertRaises(RuntimeError):settle(self.path,'alice','rollback',1,encounter_report=report)
        self.assertEqual(WalletStore(self.path).ensure('alice').credits,before);self.assertFalse(self.materials())
        settle(self.path,'alice','rollback',1,encounter_report=report);settle(self.path,'alice','rollback',1,encounter_report=report)
        self.assertEqual({i.template_id:i.count for i in self.materials()},{65487:2,65488:4})

    def test_client_materials_and_unchanged_denver_resources(self):
        client=ROOT/'reports/forest-biomes/client/base'
        items=ET.parse(client/'shared config/items.xml').getroot()
        for identity in (65487,65488):
            node=items.find(f"item[@id='{identity}']");values={v.get('key'):v.get('val') for v in node}
            self.assertEqual(values['stackable'],'1');self.assertNotIn('itype',values)
            self.assertTrue((client/'items'/values['image']).exists())
        ground=ET.parse(client/'ground.xml').getroot()
        original=ET.parse(ROOT/'reports/forest-biomes/source/base/ground.xml').getroot()
        self.assertEqual([b.attrib for b in ground.find("ground[@id='3']")],[b.attrib for b in original.find("ground[@id='3']")])
        self.assertEqual([len(ground.findall(f"ground[@id='{i}']")) for i in (7,8,9)],[1,1,1])

if __name__=='__main__':unittest.main()
