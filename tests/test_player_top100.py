from dataclasses import replace
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest

from tio.protocol.binary import PacketError
from tio.protocol.player_top100 import SORTS,PlayerRating,decode_request,encode_request,encode_ratings,decode_ratings,encode_world_rows
from tio import world_completion as world
from tio.protocol.pet_info import decode_pet_info,encode_pet_info


class PlayerTop100Tests(unittest.TestCase):
    def test_original_requests_all_combo_selectors_are_checked(self):
        for selector in range(9):self.assertEqual(decode_request(encode_request(selector)),selector)
        self.assertEqual([SORTS[i] for i in range(6)],['rating','wins','damage','kills','experience','rank'])
        for raw in (b'',b'\xa4',b'\xa405',b'\xa4\x09',b'\xa4\x05\0',b'\xf9\x01'):
            with self.assertRaises(PacketError):decode_request(raw)

    def test_native_rows_roundtrip_signed_rank_empty_and_maximum(self):
        row=PlayerRating(b'Alice',b'Clan',11,0xdeadbeef,12,20,13,14,15,16,-17,8,-19,20,21,22,23)
        for selector in range(9):
            self.assertEqual(decode_ratings(encode_ratings(selector,(row,))),(selector,(row,)))
            self.assertEqual(encode_ratings(selector,()),bytes([0xa5,selector,0,0]))
        rows=tuple(PlayerRating(f'Player{i:03}'.encode(),rating=i) for i in range(100))
        self.assertEqual(decode_ratings(encode_ratings(0,rows))[1],rows)
        with self.assertRaises(PacketError):encode_ratings(0,rows+(rows[0],))

    def test_malformed_responses_names_counters_and_trailing_bytes_rejected(self):
        for row in (PlayerRating(b''),PlayerRating(b'A\0B'),PlayerRating(b'A'*17),PlayerRating(b'Alice',clan_name=b'C'*33),
                    PlayerRating(b'Alice',wins=-1),PlayerRating(b'Alice',rating=1<<31),PlayerRating(b'Alice',rank_points=-(1<<31)-1)):
            with self.assertRaises(PacketError):encode_ratings(0,(row,))
        packet=encode_ratings(5,(PlayerRating(b'Alice'),))
        for n in range(len(packet)):
            with self.assertRaises(PacketError):decode_ratings(packet[:n])
        with self.assertRaises(PacketError):decode_ratings(packet+b'\0')

    def test_world_adapter_public_whitelist_no_owner_ids_and_clamps_without_wrapping(self):
        row=dict(name=b'Alice',owner='SECRET-account-routing',password='SECRET-password',level=999,
            rank=-1,rating=1<<45,wins=1<<40,damage=1<<50,experience=123,
            kills=7,losses=9,damage_received=99,deaths=8,military_rank=14,skill=172)
        packet=encode_world_rows(0,(row,));self.assertNotIn(b'SECRET',packet)
        decoded=decode_ratings(packet)[1][0]
        self.assertEqual((decoded.rating,decoded.wins,decoded.damage_dealt,decoded.rank_points,decoded.level),
                         (0x7fffffff,0xffffffff,0xffffffff,-1,255))
        self.assertEqual((decoded.kills,decoded.losses,decoded.damage_received,decoded.deaths,decoded.trueskill),(7,9,99,8,172))

    def fixture(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);path=Path(tmp.name)/'world.sqlite3'
        db=sqlite3.connect(path);self.addCleanup(db.close)
        db.executescript('''CREATE TABLE accounts(login TEXT PRIMARY KEY);
            CREATE TABLE characters(account TEXT,slot INTEGER,name BLOB,name_key TEXT);
            CREATE TABLE owned_pets(account TEXT,pet_id INTEGER,human INTEGER,pet_packet BLOB,inventory_packet BLOB,PRIMARY KEY(account,pet_id));
            CREATE TABLE soldier_ratings(account TEXT,pet_id INTEGER,rating INTEGER);
            CREATE TABLE battle_rewards(account TEXT,result INTEGER,calculation TEXT);
            CREATE TABLE player_battle_statistics(account TEXT,damage_dealt INTEGER,damage_received INTEGER,kills INTEGER,deaths INTEGER);
            CREATE TABLE player_statistics_baselines(account TEXT,kills INTEGER);
            CREATE TABLE achievement_counters(account TEXT,metric TEXT,value INTEGER);
            CREATE TABLE achievement_awards(account TEXT,id INTEGER,body TEXT,notified INTEGER);
            CREATE TABLE ranked_players(account TEXT,skill INTEGER,league INTEGER,wins INTEGER,losses INTEGER,draws INTEGER);
        ''')
        trial=json.loads((world.ROOT/'evidence/owned_pet_trial.json').read_text())
        pet=decode_pet_info(bytes.fromhex(trial['packet_hex']),human_equipment=True)
        for owner,values in (('alice',(1,300,100,3,10,3,80,4,40)),('bob',(2,-30,900,9,100,1,7,2,18)),('unranked',(0,0,0,0,0,0,0,0,0))):
            rating,points,xp,wins,dealt,kills,received,deaths,oldkills=values
            db.execute('INSERT INTO accounts VALUES (?)',(owner,))
            db.execute('INSERT INTO characters VALUES (?,1,?,?)',(owner,owner.title().encode(),owner))
            raw=encode_pet_info(replace(pet,fields={**pet.fields,'0x8c4bbc':1,'0x8c4bd0':points&0xffffffff,'0x8c4b05':xp}))
            db.execute('INSERT INTO owned_pets VALUES (?,1,1,?,?)',(owner,raw,b''))
            db.execute('INSERT INTO soldier_ratings VALUES (?,1,?)',(owner,rating))
            db.executemany('INSERT INTO battle_rewards VALUES (?,1,?)',[(owner,'{}')]*wins)
            db.execute('INSERT INTO battle_rewards VALUES (?,0,?)',(owner,'{}'))
            db.execute('INSERT INTO battle_rewards VALUES (?,1,?)',(owner,'{"wager":true}'))
            db.execute('INSERT INTO player_battle_statistics VALUES (?,?,?,?,?)',(owner,dealt,received,kills,deaths))
            db.execute('INSERT INTO player_statistics_baselines VALUES (?,?)',(owner,oldkills))
            db.execute('INSERT INTO achievement_counters VALUES (?,"kills",99999)',(owner,))
        db.execute('INSERT INTO achievement_awards VALUES ("alice",1,?,0)',(json.dumps({'prizes':[{'kind':3,'value':75}]}),))
        db.execute('INSERT INTO ranked_players VALUES ("alice",173,3,1,0,0)')
        db.execute('INSERT INTO ranked_players VALUES ("bob",160,3,1,0,0)')
        db.execute('INSERT INTO ranked_players VALUES ("unranked",399,3,0,0,0)')
        db.commit();return db,path

    def test_real_backend_all_six_sorts_stats_bonus_negative_rank_and_no_writes(self):
        db,path=self.fixture();before=path.read_bytes()
        for selector,name in ((0,b'Alice'),(1,b'Bob'),(2,b'Bob'),(3,b'Alice'),(4,b'Bob'),(5,b'Alice')):
            rows=world.player_top100(path,sort=SORTS[selector]);packet=encode_world_rows(selector,rows)
            self.assertEqual(decode_ratings(packet)[1][0].name,name)
        rows={r['name']:r for r in world.player_top100(path)}
        self.assertEqual((rows[b'Alice']['rating'],rows[b'Alice']['kills'],rows[b'Alice']['damage_received'],rows[b'Alice']['deaths'],rows[b'Alice']['losses']),(76,43,80,4,1))
        self.assertEqual(rows[b'Bob']['rank'],-10)
        self.assertEqual(path.read_bytes(),before)

    def test_leagues_only_ranked_matches_actual_skill_filter_and_stable_ties(self):
        db,path=self.fixture();before=path.read_bytes()
        self.assertEqual([r['name'] for r in world.player_top100(path,sort='bronze')],[b'Alice',b'Bob'])
        self.assertEqual(world.player_top100(path,sort='gold'),())
        self.assertEqual(path.read_bytes(),before)
        db.execute('UPDATE ranked_players SET skill=173 WHERE account="bob"');db.commit()
        self.assertEqual([r['name'] for r in world.player_top100(path,sort='bronze')],[b'Alice',b'Bob'])
        db.execute('UPDATE ranked_players SET league=2 WHERE account="bob"');db.commit()
        self.assertEqual([r['name'] for r in world.player_top100(path,sort='silver')],[b'Bob'])

    def test_total_rating_signed_bounds_and_current_roster_only(self):
        db,path=self.fixture()
        db.execute('UPDATE soldier_ratings SET rating=4294967295 WHERE account="bob"')
        db.execute('UPDATE soldier_ratings SET rating=-9999999999 WHERE account="unranked"');db.commit()
        rows={r['name']:r for r in world.player_top100(path)}
        self.assertEqual(rows[b'Bob']['rating'],0x7fffffff);self.assertEqual(rows[b'Unranked']['rating'],-(1<<31))
        db.execute('DELETE FROM owned_pets WHERE account="bob"');db.commit()
        rows={r['name']:r for r in world.player_top100(path)}
        self.assertEqual((rows[b'Bob']['rating'],rows[b'Bob']['experience'],rows[b'Bob']['rank']),(0,0,0))


if __name__=='__main__':unittest.main()
