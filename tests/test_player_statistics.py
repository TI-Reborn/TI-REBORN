from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from tio.battle_rewards import settle
from tio.player_statistics import save_online,battle_report
from tio.owned_pets import OwnedPetStore
from tio.wallets import WalletStore
from server.accounts import Accounts
from server.public_profile import read_profile
import json


class PlayerStatisticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'players.sqlite3'
        trial=json.loads((Path(__file__).resolve().parents[1]/'evidence/owned_pet_trial.json').read_text())
        for name in ('Alice','Bob'):
            Accounts(self.path).create(name.lower(),'password123456',character=name)
            OwnedPetStore(self.path).ensure(name.lower(),bytes.fromhex(trial['packet_hex']),bytes.fromhex(trial['inventory_packet_hex']),human=True)
            WalletStore(self.path).ensure(name.lower())

    def test_transaction_retry_isolation_online_and_read_only(self):
        report=({'kills':2,'losses':1,'damage_dealt':90,'damage_received':70},{1:(2,1)})
        for _ in range(2):settle(self.path,'alice','match',1,statistics_report=report,now=100)
        settle(self.path,'bob','match',0,statistics_report=({'losses':2},{1:(0,2)}),now=100)
        save_online(self.path,'alice',3590);save_online(self.path,'alice',20)
        before=self.path.read_bytes();a=read_profile(self.path,name=b'Alice');b=read_profile(self.path,name=b'Bob')
        self.assertEqual((a.wins,a.losses,a.kills,a.deaths,a.damage_dealt,a.damage_received,a.rating,a.online_seconds),(1,0,2,1,90,70,1,3610))
        self.assertEqual((b.wins,b.losses,b.deaths,b.rating,b.online_seconds),(0,1,2,-2,0))
        self.assertEqual(len(a.mercenaries),1)
        self.assertEqual(before,self.path.read_bytes())

    def test_unowned_actor_rolls_back_entire_reward(self):
        before=WalletStore(self.path).ensure('alice')
        with self.assertRaises(ValueError):
            settle(self.path,'alice','bad',1,statistics_report=({'kills':5},{99:(5,0)}))
        self.assertEqual(before,WalletStore(self.path).ensure('alice'))
        self.assertEqual(read_profile(self.path,name=b'Alice').wins,0)

    def test_firing_removes_rating_but_preserves_historical_totals(self):
        settle(self.path,'alice','match',1,statistics_report=({'kills':2},{1:(2,0)}))
        with closing(sqlite3.connect(self.path)) as db,db:db.execute('DELETE FROM owned_pets WHERE account=?',('alice',))
        a=read_profile(self.path,name=b'Alice')
        self.assertEqual((a.rating,a.kills,a.wins,a.mercenaries),(0,2,1,()))

    def test_existing_achievement_kills_are_imported_once(self):
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('CREATE TABLE achievement_counters(account TEXT,metric TEXT,value INTEGER,PRIMARY KEY(account,metric))')
            db.execute("INSERT INTO achievement_counters VALUES ('alice','kills',17)")
        self.assertEqual(read_profile(self.path,name=b'Alice').kills,17)
        settle(self.path,'alice','new',1,statistics_report=({'kills':2},{1:(2,0)}))
        with closing(sqlite3.connect(self.path)) as db,db:db.execute("UPDATE achievement_counters SET value=19")
        settle(self.path,'alice','again',1,statistics_report=({'kills':1},{1:(1,0)}))
        self.assertEqual(read_profile(self.path,name=b'Alice').kills,20)

    def test_shared_ids_map_to_local_soldiers_and_bots_cannot_create_rating(self):
        from types import SimpleNamespace
        actors={11:SimpleNamespace(owner_id=101,health=100),12:SimpleNamespace(owner_id=102,health=0),
                13:SimpleNamespace(owner_id=103,health=0)}
        combat=SimpleNamespace(field=SimpleNamespace(_actors=actors,actor=lambda i:actors[i]),
            persistence={11:('db','alice'),12:('db','bob')},storage_ids={11:1,12:1,13:1},
            rank_kills=[(11,12),(11,13)],statistics={101:{'kills':2},102:{'losses':1}})
        self.assertEqual(battle_report(combat,101),({'kills':2},{1:[1,0]}))
        self.assertEqual(battle_report(combat,102),({'losses':1},{1:[0,1]}))
