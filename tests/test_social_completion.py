"""Authenticated social boundaries, real stores, shared transactions and clocks."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import importlib
import json
from pathlib import Path
import sqlite3
import sys
from types import ModuleType,SimpleNamespace
import unittest

from tio import social_completion as social
from tio.db_transaction import transaction
from tio.protocol.binary import Reader
from test_warehouse_completion import WarehouseCompletionTests as WarehouseFixture,WAREHOUSE
from server.social_commands import command

ROOT=Path(__file__).resolve().parents[1]


def runtime(name):
    actual=importlib.import_module(name)
    if hasattr(importlib.import_module('tio.clans'),'social_completion_installed'):
        return actual
    path=ROOT/'reports/gameplay-followup/stage3-social/runtime'/Path(*name.split('.')).with_suffix('.py')
    module=ModuleType(name.rsplit('.',1)[0]+'._social_'+name.rsplit('.',1)[1]);module.__package__=name.rsplit('.',1)[0]
    module.__file__=str(ROOT/Path(*name.split('.')).with_suffix('.py'));sys.modules[module.__name__]=module
    exec(compile(path.read_text(encoding='utf-8'),str(path),'exec'),module.__dict__)
    return module


CLANS=runtime('tio.clans');ACHIEVEMENTS=runtime('tio.achievements')
ALLIANCE=runtime('server.alliance_service');ECONOMY=runtime('server.economy_runtime')


class SocialCompletionTests(unittest.TestCase):
    def setUp(self):
        self.fixture=WarehouseFixture(methodName='runTest');self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.path=self.fixture.path;self.now=1000
        self.clans=CLANS.ClansStore(self.path,clock=lambda:self.now)
        self.achievements=ACHIEVEMENTS.AchievementStore(self.path)
        self.session=SimpleNamespace(account='alice',database=self.path)

    def rows(self):
        with closing(sqlite3.connect(self.path)) as db:
            return {name:db.execute('SELECT * FROM '+name+' ORDER BY rowid').fetchall()
                    for name, in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")}

    def public(self, account, name):
        packet=self.achievements.handle(account,b'\xb5\x01\0'+name.encode()+b'\0',account.title())
        r=Reader(packet);self.assertEqual(r.read(3),b'\xb5\x02\0')
        name=bytearray()
        while (value:=r.u8()):name.append(value)
        count=r.u32();rows=[dict(id=r.u32(),level=r.u8(),earned=r.u32()) for _ in range(count)];r.finish()
        return bytes(name),rows

    def alliance(self):
        from tio.alliances import AlliancesStore
        gamma=self.clans.create('carol',b'Gamma')
        with transaction(self.path) as db:
            db.execute('UPDATE clans SET level=1,credits=500000,influence=100000')
        store=AlliancesStore(self.path,clock=lambda:self.now)
        identity=store.create('alice',b'Both Together');store.invite('alice',gamma);store.accept('carol',1)
        return store,identity

    def test_foreign_native_rows_are_earned_only_and_do_not_award_or_deliver(self):
        with transaction(self.path) as db: ACHIEVEMENTS.update(db,'bob',add={'kills':10})
        before=self.rows();name,rows=self.public('alice','bOB')
        self.assertEqual(name,b'Bob');self.assertEqual(len(rows),58)
        self.assertEqual(next(r['earned'] for r in rows if r['id']==4),1)
        self.assertEqual(self.rows(),before)
        self.assertEqual(WAREHOUSE.WarehouseStore(self.path).items('bob'),())
        # Foreign viewing does not manufacture snapshot awards from Bob's money.
        self.public('carol','Bob');self.assertEqual(self.rows(),before)
        self.achievements.flush('bob')
        self.assertEqual(len(WAREHOUSE.WarehouseStore(self.path).items('bob')),5)

    def test_self_private_layout_and_owner_flush_keep_other_character_pending(self):
        with transaction(self.path) as db: ACHIEVEMENTS.update(db,'bob',add={'kills':10})
        self.achievements.handle('alice',b'\xb5\x01\0Alice\0','Bob')
        self.achievements.flush('alice')
        with transaction(self.path) as db:
            self.assertEqual(db.execute('SELECT delivered FROM achievement_prizes WHERE account=? AND id=4 AND position=0',('bob',)).fetchone()[0],0)
        private=self.achievements.handle('bob',b'\xb5\x01\0bob\0','Alice')
        self.assertGreater(len(private),3+4+4+58*9)
        self.assertIn(b'Bob\0',private[:10])

    def test_missing_malformed_foreign_and_own_clan_name_collision_fail_closed(self):
        with transaction(self.path) as db:
            db.execute('UPDATE clans SET name=?,name_key=? WHERE id=?',(b'Bob','bob',self.fixture.clan))
        before=self.rows()
        for packet in (b'\xb5\x01\0Bob\0',b'\xb5\x01\0Nobody\0',b'\xb5\x01\1Bob\0',b'\xb5\x01\0Bob\0extra'):
            with self.assertRaises(ValueError): self.achievements.handle('alice',packet,'Alice')
        self.assertEqual(self.rows(),before)

    def test_free_any_level_join_and_same_decision_replay_spend_nothing(self):
        # A newly invited account may join without the founder's level4 gate.
        self.fixture.location('carol',3)
        from tio.protocol.pet_info import decode_pet_info,encode_pet_info
        pet=decode_pet_info(self.fixture.pet,human_equipment=True);pet.fields['0x8c4aef']=1
        with transaction(self.path) as db:
            db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=?',(encode_pet_info(pet),'carol'))
        self.clans.invite('alice',b'Carol');before=self.rows()['wallets']
        cid=self.clans.accept('carol',1);self.assertEqual(self.clans.accept('carol',1),cid)
        self.assertEqual(self.rows()['wallets'],before)
        with transaction(self.path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM clan_ledger WHERE operation='join' AND account='carol'").fetchone()[0],1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM social_completion_receipts WHERE operation='clan_join' AND account='carol'").fetchone()[0],1)

    def test_leave_kick_cooldown_no_legacy_backfill_or_replayed_extension(self):
        with transaction(self.path) as db:
            self.assertEqual(social.clan_delay(db,'bob',now=self.now)['remaining_seconds'],0)
        self.clans.remove('bob');before=self.rows()
        with self.assertRaises(ValueError): self.clans.remove('bob')
        self.assertEqual(self.rows(),before)
        for operation in (lambda:self.clans.invite('alice',b'Bob'),lambda:self.clans.create('bob',b'New Clan')):
            with self.assertRaises(ValueError):operation()
        self.assertEqual(self.rows(),before)
        with transaction(self.path) as db:
            self.assertEqual(social.clan_delay(db,'bob',now=self.now)['remaining_seconds'],86400)
            self.assertFalse(social.clan_delay(db,'bob',now=self.now-100)['can_join'])
            self.assertTrue(social.clan_delay(db,'alice',now=self.now)['can_join'])
            social.departed(db,'bob',self.fixture.clan,'leave',now=self.now+100)
            self.assertEqual(social.clan_delay(db,'bob',now=self.now)['remaining_seconds'],86400)
        self.now+=86400
        self.clans.invite('alice',b'Bob');self.clans.accept('bob',1)
        self.clans.remove('alice',b'Bob')
        with transaction(self.path) as db:
            self.assertEqual(db.execute('SELECT reason,until FROM clan_player_cooldowns WHERE account=?',('bob',)).fetchone(),('kick',self.now+86400))

    def test_cooldown_accept_bypass_rollback_and_registered_roster_are_blocked(self):
        self.clans.remove('bob')
        with transaction(self.path) as db:
            db.execute('INSERT INTO clan_invitations VALUES (?,?,?,?)',('bob',self.fixture.clan,'alice',self.now+90000))
        before=self.rows()
        with self.assertRaises(ValueError):self.clans.accept('bob',1)
        self.assertEqual(self.rows(),before)
        with transaction(self.path) as db:
            db.execute('CREATE TABLE warfare_clan_locks(clan_id INTEGER PRIMARY KEY)')
            db.execute('INSERT INTO warfare_clan_locks VALUES (?)',(self.fixture.clan,))
        before=self.rows()
        with self.assertRaises(ValueError):self.clans.remove('alice',b'Bob')
        self.assertEqual(self.rows(),before)
        with self.assertRaises(RuntimeError):
            with transaction(self.path) as db:
                db.execute('DELETE FROM warfare_clan_locks')
                self.clans.invite('alice',b'Carol');self.clans.accept('carol',1);self.clans.remove('carol')
                raise RuntimeError('Reject outer action')
        self.assertEqual(self.rows(),before)

    def test_concurrent_join_replay_uses_one_actual_shared_membership(self):
        self.clans.invite('alice',b'Carol')
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:self.clans.accept('carol',1),range(2)))
        self.assertEqual(results,[self.fixture.clan]*2)
        with transaction(self.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM clan_members WHERE account=?',('carol',)).fetchone()[0],1)

    def test_alliance_cancel_actual_cohort_name_funds_and_retry(self):
        store,identity=self.alliance();store.dissolve('alice');before=self.rows()
        with transaction(self.path) as db:
            for account,name in (('bob','Both Together'),('carol','Both Together'),('alice','Wrong Name')):
                with self.assertRaises(ValueError):social.alliance_cancel(db,self.path,account,name,now=self.now)
        self.assertEqual(self.rows(),before)
        with transaction(self.path) as db:
            first=social.alliance_cancel(db,self.path,'alice','Both Together',now=self.now)
            replay=social.alliance_cancel(db,self.path,'alice','Both Together',now=self.now)
        self.assertFalse(first['replayed']);self.assertTrue(replay['replayed'])
        self.assertEqual(store.info('carol')['state'],'active');self.assertEqual(store.info('alice')['id'],identity)
        self.assertEqual(self.rows()['wallets'],before['wallets'])
        self.assertEqual(self.rows()['alliance_members'],before['alliance_members'])
        self.assertEqual(self.rows()['clan_items'],before['clan_items'])

    def test_alliance_cancel_deadline_registered_guard_and_outer_rollback(self):
        store,identity=self.alliance();store.dissolve('alice');before=self.rows()
        with self.assertRaises(RuntimeError):
            with transaction(self.path) as db:
                social.alliance_cancel(db,self.path,'alice','Both Together',now=self.now)
                raise RuntimeError('Rejected after cancellation')
        self.assertEqual(self.rows(),before)
        with transaction(self.path) as db:
            db.execute('CREATE TABLE warfare_clan_locks(clan_id INTEGER PRIMARY KEY)')
            db.execute('INSERT INTO warfare_clan_locks VALUES (?)',(self.fixture.clan,))
        before=self.rows()
        with self.assertRaises(ValueError):
            with transaction(self.path) as db:social.alliance_cancel(db,self.path,'alice','Both Together',now=self.now)
        self.assertEqual(self.rows(),before)
        with transaction(self.path) as db:
            db.execute('DELETE FROM warfare_clan_locks')
        self.now+=3*86400
        before=self.rows()
        with self.assertRaises(ValueError):
            with transaction(self.path) as db:social.alliance_cancel(db,self.path,'alice','Both Together',now=self.now)
        self.assertEqual(self.rows(),before)

    def test_private_typed_command_status_busy_gate_and_public_isolation(self):
        store,_=self.alliance();store.dissolve('alice')
        def packet(text):return b'\x21\0'+text.encode('utf-16le')+b'\0\0'
        self.assertTrue(ECONOMY.private_command(packet('!clan status')))
        with transaction(self.path) as db:
            replies=command(db,self.session,'!clan status',city_idle=False,now=self.now)
            self.assertTrue(all(p[:1]==b'\x22' and p[5]==4 for p in replies))
            with self.assertRaises(ValueError):command(db,self.session,'!clan alliancecancel Both Together',city_idle=False,now=self.now)
            result=command(db,self.session,'!clan alliancecancel Both Together',city_idle=True,now=self.now)
            self.assertEqual(len(result),1)
        self.assertEqual(store.info('carol')['state'],'active')

    def test_native_dissolution_request_retry_does_not_toggle_and_other_account_sees_cancel(self):
        from unittest.mock import patch
        store,_=self.alliance()
        session=SimpleNamespace(account='alice',database=self.path,alliances_store=store)
        packets=[];notify=[]
        with patch.object(ALLIANCE,'require_city'),patch.object(ALLIANCE,'notify',side_effect=lambda *_:notify.append(True)),patch.object(ALLIANCE,'enqueue',side_effect=lambda _p,_s,*p:packets.extend(p)):
            self.assertTrue(ALLIANCE.handle(None,session,b'\xaf\x0c'))
            self.assertEqual(store.info('carol')['state'],'dissolving')
            before=self.rows()
            self.assertTrue(ALLIANCE.handle(None,session,b'\xaf\x0c'))
            self.assertEqual(self.rows(),before)
            self.assertIn('!clan alliancecancel Both Together'.encode('utf-16le'),packets[-1])
            self.assertEqual(packets[-1][5],4)
        with transaction(self.path) as db:
            command(db,self.session,'!clan alliancecancel Both Together',city_idle=True,now=self.now)
        self.assertEqual(store.info('carol')['state'],'active')
        self.assertEqual(len(notify),2)

    def test_clan_dissolution_preserves_items_and_initialization_never_backfills_legacy_departures(self):
        with transaction(self.path) as db:
            db.execute("INSERT INTO clan_ledger(clan_id,account,operation,detail,created) VALUES (?,?,?,?,?)",(self.fixture.clan,'carol','leave','carol',self.now))
        before=self.rows()
        CLANS.ClansStore(self.path,clock=lambda:self.now)
        self.assertEqual(self.rows(),before)
        cid=self.clans.create('carol',b'Empty Clan')
        before_items={n:self.rows()[n] for n in ('warehouse_items','owned_pets','clan_items')}
        self.clans.dissolve('carol',cid)
        self.assertEqual({n:self.rows()[n] for n in before_items},before_items)
        with transaction(self.path) as db:
            self.assertEqual(social.clan_delay(db,'carol',now=self.now)['remaining_seconds'],86400)
        with self.assertRaises(ValueError):self.clans.create('carol',b'Recreated Clan')


if __name__=='__main__':unittest.main()
