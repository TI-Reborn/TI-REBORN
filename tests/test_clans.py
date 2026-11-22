from wallet_fixture import fund_wallet
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from collections import deque
import json,sqlite3,tempfile,unittest
from tio.clans import *
from tio.wallets import WalletStore
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.item_list import decode_item_list,encode_item_list
from tio.protocol.warehouse import decode_warehouse_list
from tio.protocol.clans import decode_request,encode_info,encode_members
from tio.protocol.warehouse_transfer import WarehouseTransfer,encode_warehouse_transfer
from tio.warehouse_service import transfer_private_items


class ClanTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.path=Path(folder.name)/'clans.sqlite3'
        trial=json.loads((Path(__file__).resolve().parents[1]/'evidence/owned_pet_trial.json').read_text())
        pet=decode_pet_info(bytes.fromhex(trial['packet_hex']),human_equipment=True)
        pet.fields['0x8c4aef']=4
        item=decode_item_list(bytes.fromhex(trial['inventory_packet_hex']))[1][0]
        self.item=replace(item,unknown_u8_01=0,location_raw=0,unknown_u32_01=10)
        self.pets=OwnedPetStore(self.path)
        for account in ('alice','bob','carol'):
            self.pets.ensure(account,encode_pet_info(pet),encode_item_list(1,(self.item,)),human=True)
            fund_wallet(self.path, account, credits=10_000, gold=10_000)
        with closing(connect(self.path)) as db,db:
            db.execute('CREATE TABLE characters(account TEXT,slot INTEGER,name BLOB,name_key TEXT UNIQUE)')
            db.executemany('INSERT INTO characters VALUES (?,1,?,?)',[(a,a.title().encode(),a) for a in ('alice','bob','carol')])
        self.store=ClansStore(self.path)
        self.cid=self.store.create('alice',b'Alpha')
        self.join('bob')

    def join(self,account):
        self.store.invite('alice',account.encode());self.store.accept(account,1)

    def rights(self,account,rights):
        self.store.permissions('alice',self.store.info(account)['member_id'],rights,2)

    def exchange(self,account,kind=1,deposits=(),withdrawals=()):
        return self.store.exchange(account,1,kind,deposits=deposits,withdrawals=withdrawals)

    def test_creation_level_names_and_unique_membership(self):
        with self.assertRaises(ClanRejected):self.store.create('bob',b'Other')
        with self.assertRaises(ClanRejected):self.store.create('carol',b'ALPHA')
        with closing(connect(self.path)) as db,db:
            raw=db.execute("SELECT pet_packet FROM owned_pets WHERE account='carol'").fetchone()[0]
            pet=decode_pet_info(raw,human_equipment=True);pet.fields['0x8c4aef']=3
            db.execute("UPDATE owned_pets SET pet_packet=? WHERE account='carol'",(encode_pet_info(pet),))
        with self.assertRaises(ClanRejected):self.store.create('carol',b'Other')
        self.assertEqual(self.store.info('bob')['id'],self.cid)

    def test_expired_invite_and_revoked_inviter_do_not_join(self):
        self.rights('bob',DEFAULT_RIGHTS|INVITE)
        self.store.invite('bob',b'Carol',now=100)
        with self.assertRaises(ClanRejected):self.store.accept('carol',1,now=401)
        self.rights('bob',DEFAULT_RIGHTS)
        with self.assertRaises(ClanRejected):self.store.accept('carol',1,now=101)
        self.assertIsNone(self.store.info('carol'))

    def test_rights_cannot_cross_clans_or_grant_leadership(self):
        other=self.store.create('carol',b'Other')
        with self.assertRaises(ClanRejected):self.store.permissions('alice',self.store.info('carol')['member_id'],KNOWN_RIGHTS,1)
        with self.assertRaises(ClanRejected):self.store.transfer_leader('alice',b'Carol')
        self.rights('bob',KNOWN_RIGHTS)
        with self.assertRaises(ClanRejected):self.store.permissions('bob',self.store.info('alice')['member_id'],0,0)
        with self.assertRaises(ClanRejected):self.store.remove('bob',b'Alice')
        with self.assertRaises(ClanRejected):self.store.dissolve('bob',self.cid)

    def test_shared_items_remap_ids_and_conserve_metadata(self):
        _,items=self.exchange('alice',deposits=((1001,4),))
        key=items[0].instance_id
        self.assertNotEqual(key,1001)
        self.assertEqual(items,self.store.items('bob',1))
        with self.assertRaises(ClanRejected):self.exchange('bob',withdrawals=((key,2),))
        self.rights('bob',DEFAULT_RIGHTS|WITHDRAW_WAREHOUSE)
        inv,items=self.exchange('bob',withdrawals=((key,2),))
        actual=decode_item_list(inv)[1]
        self.assertEqual(sum(i.count for i in actual),12)
        self.assertEqual(sum(i.count for i in items),2)
        self.assertTrue(all(i.unknown_words==self.item.unknown_words for i in (*actual,*items)))
        self.assertEqual(len({i.instance_id for i in actual}),len(actual))
        self.store.remove('alice',b'Bob')
        with self.assertRaises(ClanRejected):self.exchange('bob',withdrawals=((key,1),))
        self.assertEqual(ClansStore(self.path).items('alice',1),items)

    def test_concurrent_withdrawals_cannot_duplicate_shared_item(self):
        _,items=self.exchange('alice',deposits=((1001,10),));key=items[0].instance_id
        self.rights('bob',DEFAULT_RIGHTS|WITHDRAW_WAREHOUSE)
        def take(account):
            try:self.exchange(account,withdrawals=((key,10),));return True
            except ClanRejected:return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(take,('alice','bob'))),[False,True])
        self.assertEqual(self.store.items('alice',1),())
        self.assertEqual(sum(i.count for a in ('alice','bob') for i in decode_item_list(self.pets.inventory(a,1))[1]),20)

    def test_warehouse_log_is_private_and_keeps_name_and_template_after_withdrawal(self):
        from server.social_commands import command
        from tio.db_transaction import transaction

        def read(account, text='!clan log'):
            with transaction(self.path) as db:
                packets=command(db,SimpleNamespace(account=account),text,city_idle=False)
                self.assertTrue(all(p[:1]==b'\x22' and p[5]==4 for p in packets))
                return '\n'.join(p[p.index(b'\0',6)+1:-2].decode('utf-16le') for p in packets)

        _,stock=self.exchange('alice',deposits=((1001,4),))
        key=stock[0].instance_id
        self.rights('bob',DEFAULT_RIGHTS|WITHDRAW_WAREHOUSE)
        self.exchange('bob',withdrawals=((key,4),))
        self.exchange('bob',2,deposits=((0xffff0001,100),))
        with transaction(self.path) as db:
            db.execute("UPDATE characters SET name=? WHERE account='bob'",(b'Bobby',))
            record(db,self.cid,'alice','items','1:[(12345, 2)]:[]')
        log=read('bob')
        from tio.item_catalog import items_root
        item_name=items_root().find(f"item[@id='{self.item.template_id}']").get('name')
        self.assertIn('Bob забрал',log)
        self.assertIn(f'Alice положил {item_name} ×4',log)
        self.assertIn('#12345 ×2',log)
        self.assertNotIn('Bobby',log)
        self.assertNotIn('100 кредит',log)
        with transaction(self.path) as db:
            for _ in range(5):
                record(db,self.cid,'alice','items','1:[(6789, 1)]:[]')
        self.assertIn('!clan log 2',read('alice'))
        self.assertIn('Bob забрал',read('alice','!clan log 2'))
        with self.assertRaises(ClanRejected):read('carol')
        self.rights('bob',VIEW_SAFE)
        with self.assertRaises(ClanRejected):read('bob')

    def test_treasury_native_arrays_rights_and_conservation(self):
        self.exchange('bob',2,deposits=((0xffff0001,500),(0xffff0002,100)))
        self.assertEqual((self.store.info('alice')['credits'],self.store.info('alice')['gold']),(500,100))
        packets=self.store.warehouse_packets('alice',2)
        self.assertEqual([(i.template_id,i.count) for i in decode_warehouse_list(packets[0])[3]],[(1,500),(2,100)])
        with self.assertRaises(ClanRejected):self.exchange('bob',2,withdrawals=((0xffff0001,1),))
        self.rights('bob',DEFAULT_RIGHTS|WITHDRAW_CREDITS)
        self.exchange('bob',2,withdrawals=((0xffff0001,100),))
        self.assertEqual(WalletStore(self.path).ensure('bob').credits,9600)
        self.assertEqual(self.store.info('alice')['credits'],400)
        self.assertEqual(WalletStore(self.path).ensure('alice').repair_points,0)
        self.rights('bob',VIEW_WAREHOUSE)
        self.assertEqual(WalletStore(self.path).ensure('bob').unknown_u32_08,0)
        self.assertEqual(WalletStore(self.path).ensure('carol').unknown_u32_08,0)
        with self.assertRaises(ClanRejected):self.store.items('bob',2)
        with self.assertRaises(ClanRejected):self.store.dissolve('alice',self.cid)

    def test_concurrent_treasury_withdrawals_and_overdraft(self):
        self.exchange('alice',2,deposits=((0xffff0001,10000),))
        self.rights('bob',DEFAULT_RIGHTS|WITHDRAW_CREDITS)
        def take(account):
            try:self.exchange(account,2,withdrawals=((0xffff0001,8000),));return True
            except ClanRejected:return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(take,('alice','bob'))),[False,True])
        self.assertEqual(self.store.info('alice')['credits'],2000)
        self.assertEqual(sum(WalletStore(self.path).ensure(a).credits for a in ('alice','bob'))+2000,20000)

    def test_asset_projection_clears_stale_funds_after_revocation_or_exit(self):
        from tio.protocol.asset_count import AssetCount
        stale=AssetCount(10000,10000,unknown_u32_08=500,unknown_u32_09=100)
        self.rights('bob',VIEW_WAREHOUSE)
        with closing(connect(self.path)) as db:
            for owner in ('bob','carol'):
                result=project_assets(db,owner,stale)
                self.assertEqual((result.unknown_u32_08,result.unknown_u32_09),(0,0))
                self.assertEqual((result.credits,result.gold),(10000,10000))

    def test_failed_audit_rolls_back_money_inventory_and_sequence(self):
        before=self.pets.inventory('alice',1),WalletStore(self.path).ensure('alice'),self.store.info('alice')
        with closing(connect(self.path)) as db,db:
            db.execute("CREATE TRIGGER fail_audit BEFORE INSERT ON clan_ledger BEGIN SELECT RAISE(ABORT,'test'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.exchange('alice',2,deposits=((0xffff0001,50),))
        after=self.pets.inventory('alice',1),WalletStore(self.path).ensure('alice'),self.store.info('alice')
        self.assertEqual(before,after)

    def test_leader_transfer_leave_and_empty_dissolution(self):
        self.store.transfer_leader('alice',b'Bob')
        self.assertEqual(self.store.info('alice')['leader'],'bob')
        with self.assertRaises(ClanRejected):self.store.dissolve('alice',self.cid)
        self.store.remove('alice')
        self.store.dissolve('bob',self.cid)
        self.assertIsNone(self.store.info('bob'))
        self.assertGreater(self.store.create('carol',b'Alpha'),self.cid)

    def test_protocol_lengths_and_wire_transfer(self):
        for packet in (b'\x52Abc\0x',b'\x98'+bytes(8),b'\x53',b'\x60\0',b'\x5d\1\0'):
            with self.assertRaises(ValueError):decode_request(packet)
        self.assertEqual(decode_request(b'\x53'+self.cid.to_bytes(4,'little')),(0x53,(self.cid,)))
        packet=encode_warehouse_transfer(WarehouseTransfer(2,1,((0xffff0001,50),),()))
        replies=transfer_private_items(self.path,'bob',packet,capacity=32)
        self.assertEqual(decode_warehouse_list(replies[1])[0],2)
        self.assertEqual(replies[-1][:2],b'\xc8\x39')
        projection=project_inventory(self.path,'bob',replies[0])
        money=[i for i in decode_item_list(projection)[1] if i.instance_id in MONEY_IDS]
        self.assertEqual([(i.template_id,i.count) for i in money],[(1,9950),(2,10000)])
        self.assertFalse(any(i.instance_id in MONEY_IDS for i in decode_item_list(self.pets.inventory('bob',1))[1]))

    def test_repair_points_use_native_hidden_currency_type_in_both_catalogues(self):
        from xml.etree import ElementTree as ET
        from tio.item_presentation import NEW, ORIGINAL, items_xml

        for interface in (NEW, ORIGINAL):
            with self.subTest(interface=interface):
                root = ET.fromstring(items_xml(interface))
                item = root.find(f"item[@id='{REPAIR_TEMPLATE}']/value[@key='itype']")
                self.assertIsNotNone(item)
                self.assertEqual(item.get('val'), 'repairpoints')

    def test_clan_chat_never_reaches_other_account(self):
        from server.presence import Presence
        from tio.protocol.presence import Player
        hub=Presence();sessions=[]
        class Session:pass
        for i,a in enumerate(('alice','bob','carol')):
            s=Session();s.account=a;s.database=self.path;sessions.append(s)
            hub.players[s]=(3,Player(i+1,a.encode()));hub.messages[s]=deque()
        request=b'\x21\2'+'Private'.encode('utf-16-le')+b'\0\0'
        hub.chat(sessions[0],request)
        self.assertEqual(len(hub.messages[sessions[0]]),1);self.assertEqual(len(hub.messages[sessions[1]]),1)
        self.assertFalse(hub.messages[sessions[2]])
        self.store.remove('alice',b'Bob');hub.messages[sessions[1]].clear()
        hub.chat(sessions[0],request);self.assertFalse(hub.messages[sessions[1]])

    def test_influence_and_upgrade_are_atomic_and_use_native_cost(self):
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE');settle_influence(db,'alice',{1:100000})
            db.execute("UPDATE wallets SET credits=20000 WHERE account='alice'")
        self.store.upgrade('alice',1)
        clan=self.store.info('alice')
        self.assertEqual((clan['level'],clan['influence']),(1,0))
        self.assertEqual(WalletStore(self.path).ensure('alice').credits,5000)
        with self.assertRaises(ClanRejected):self.store.upgrade('bob',1)

    def test_battle_settlement_does_not_repeat_clan_influence(self):
        from tio.battle_rewards import settle
        settle(self.path,'alice','clan-test-match',1,experience_report={1:1000})
        before=self.store.info('alice')['influence']
        self.assertEqual(before,50)
        settle(self.path,'alice','clan-test-match',1,experience_report={1:1000})
        self.assertEqual(self.store.info('alice')['influence'],before)

    def test_city_influence_reservation_zero_denver_one_and_replay(self):
        from tio.battle_rewards import settle
        from tio.reward_policy import RewardContext
        settle(self.path,'alice','starter-city',1,experience_report={1:1000},
               reward_context=RewardContext((3,),(('bob',(3,)),),True,3))
        self.assertEqual(self.store.info('alice')['influence'],0)
        inputs=dict(experience_report={1:1000},reward_context=RewardContext((4,),(('bob',(4,)),),True,2))
        settle(self.path,'alice','denver-city',1,**inputs)
        self.assertEqual(self.store.info('alice')['influence'],50)
        settle(self.path,'alice','denver-city',1,**inputs)
        self.assertEqual(self.store.info('alice')['influence'],50)

    def test_service_rejects_mutation_in_battle_and_on_world_map(self):
        from server.presence import Presence
        from server.clan_service import handle
        class Session:pass
        s=Session();s.account='alice';s.database=self.path;s.owned_pet_probe=True;s.probe_character_id=1
        s.arena=SimpleNamespace(rooms=SimpleNamespace(snapshot=lambda:()))
        s.survival=SimpleNamespace(searching=lambda _:False)
        s.locations=SimpleNamespace(current=lambda _:3)
        s.router=SimpleNamespace(team_arena=SimpleNamespace(busy=lambda _:True))
        hub=Presence();hub.messages[s]=deque()
        self.assertTrue(handle(hub,s,b'\x53'+self.cid.to_bytes(4,'little')))
        self.assertEqual(hub.messages[s][-1][:1],b'\xf0')
        s.router.team_arena.busy=lambda _:False;s.locations.current=lambda _:None
        self.assertTrue(handle(hub,s,b'\x53'+self.cid.to_bytes(4,'little')))
        self.assertEqual(self.store.info('alice')['id'],self.cid)

    def test_safe_rejects_wrong_categories_and_preserves_upgrade_kits(self):
        with self.assertRaises(ClanRejected):self.exchange('alice',2,deposits=((1001,1),))
        kit=replace(self.item,template_id=30)
        with closing(connect(self.path)) as db,db:
            db.execute("UPDATE owned_pets SET inventory_packet=? WHERE account='alice'",(encode_item_list(1,(kit,)),))
        _,items=self.exchange('alice',2,deposits=((1001,2),));key=items[0].instance_id
        with self.assertRaises(ClanRejected):self.exchange('bob',2,withdrawals=((key,1),))
        self.rights('bob',DEFAULT_RIGHTS|WITHDRAW_UPGRADES)
        self.exchange('bob',2,withdrawals=((key,1),))
        self.assertEqual(self.store.items('alice',2)[0].count,1)

    def test_le_kit_and_its_points_cannot_enter_clan_storage(self):
        from tio.db_transaction import transaction
        from tio.warehouse_completion import stash

        kit = replace(self.item, template_id=128, unknown_words=(1000, 1000, 1000))
        personal = encode_item_list(1, (kit,))
        with transaction(self.path) as db:
            db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=?', (personal, 'alice'))
            stash(db, 'alice', (replace(kit, instance_id=8500),), origin='test-clan-repair')
        for kind in (1, 2):
            with self.subTest(kind=kind), self.assertRaisesRegex(ClanRejected, 'Repair Kit LE'):
                self.exchange('alice', kind, deposits=((kit.instance_id, 1),))
        with self.assertRaisesRegex(ValueError, 'Недостаточно ремонтных очков'):
            self.exchange('alice', 2, deposits=((0xffff0073, 1),))
        self.assertEqual(self.store.info('bob')['repair'], 0)
        self.assertEqual(WarehouseStore(self.path).items('alice')[0].unknown_words, (1000, 1000, 1000))
        with closing(connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT inventory_packet FROM owned_pets WHERE account=?',
                                        ('alice',)).fetchone()[0], personal)

    def test_shared_repair_debits_personal_kits_and_updates_clanmates_item(self):
        from tio.db_transaction import transaction
        from tio.warehouse_completion import stash

        repair_points = 0xffff0073
        kit = replace(self.item, instance_id=8500, template_id=17, unknown_u32_01=2,
                      unknown_words=(600, 600, 600))
        coat = replace(self.item, template_id=222, unknown_u32_01=1, unknown_words=(100, 180, 180))
        with transaction(self.path) as db:
            stash(db, 'alice', (kit,), origin='test-clan-repair')
            db.execute("UPDATE owned_pets SET inventory_packet=? WHERE account='bob'", (encode_item_list(1, (coat,)),))
        _, shelf = self.exchange('bob', deposits=((coat.instance_id, 1),))
        target = shelf[0].instance_id
        self.exchange('alice', 2, deposits=((repair_points, 625),))
        self.assertEqual(sorted(i.unknown_words[0] for i in WarehouseStore(self.path).items('alice')), [575])
        self.assertEqual(self.store.info('bob')['repair'], 625)

        with self.assertRaises(ClanRejected):
            self.store.repair_warehouse_item('bob', 1, target)
        self.rights('bob', DEFAULT_RIGHTS | WITHDRAW_REPAIR)
        self.store.repair_warehouse_item('bob', 1, target)
        self.assertEqual(self.store.items('alice', 1)[0].unknown_words, (178, 178, 180))
        self.assertEqual(self.store.info('alice')['repair'], 547)
        with self.assertRaises(ValueError):
            self.store.repair_warehouse_item('bob', 1, target)
        self.assertEqual(self.store.info('alice')['repair'], 547)


if __name__=='__main__':unittest.main()
