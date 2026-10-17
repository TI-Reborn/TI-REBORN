"""Real SQLite owners, durable free choices, native resources and gate checks."""
from pathlib import Path
import tempfile,sqlite3,json,struct,zlib,unittest
from contextlib import closing
from tio import avatars
from tio.owned_pets import OwnedPetStore
from tio.wallets import WalletStore
from tio.protocol.item_list import encode_item_list
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from dataclasses import replace

ROOT=Path(__file__).resolve().parents[1]


class AvatarTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'state.db';self.store=OwnedPetStore(self.path)
        packet=bytes.fromhex(json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())['packet_hex'])
        for owner in ('alice','bob'):
            for identity in (1,2):
                pet=decode_pet_info(packet,human_equipment=True)
                pet=replace(pet,fields={**pet.fields,'0x8c43eb':identity})
                self.store.ensure(owner,encode_pet_info(pet),encode_item_list(identity,()),human=True)
            WalletStore(self.path).ensure(owner)
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('CREATE TABLE characters(account TEXT,slot INTEGER)')
            db.executemany('INSERT INTO characters VALUES (?,1)',(('alice',),('bob',)))
            db.execute('CREATE TABLE character_locations(account TEXT,town_id INTEGER)')
            db.executemany('INSERT INTO character_locations VALUES (?,3)',(('alice',),('bob',)))

    def test_choices_persist_isolate_accounts_and_never_charge_or_change_pet_data(self):
        before=self.store.list('alice');wallet=WalletStore(self.path).ensure('alice')
        avatars.assign(self.path,'alice',1,10001,allowed=True)
        avatars.assign(self.path,'alice',1,10001,allowed=True)
        avatars.assign(self.path,'bob',1,10003,allowed=True)
        self.assertEqual(avatars.selections(self.path,'alice'),{1:10001})
        self.assertEqual(avatars.selections(self.path,'bob'),{1:10003})
        self.assertEqual(self.store.list('alice'),before)
        self.assertEqual(WalletStore(self.path).ensure('alice'),wallet)
        self.assertEqual(avatars.snapshot(self.path,'alice'),avatars.encode_assignments(((1,10001),(2,0))))
        avatars.assign(self.path,'alice',1,0,allowed=True)
        self.assertEqual(avatars.selections(self.path,'alice'),{1:0})

    def test_unowned_pet_unknown_avatar_wrong_session_gate_and_travel_are_rejected(self):
        for owner,pet,avatar,allowed in (('alice',9,10001,True),('foreign',1,10001,True),('alice',1,99,True),('alice',1,10001,False)):
            with self.assertRaises(ValueError):avatars.assign(self.path,owner,pet,avatar,allowed=allowed)
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('CREATE TABLE map_journeys(account TEXT)');db.execute("INSERT INTO map_journeys VALUES ('alice')")
        with self.assertRaises(ValueError):avatars.assign(self.path,'alice',1,10001,allowed=True)
        self.assertEqual(avatars.selections(self.path,'alice'),{})

    def test_catalog_and_native_image_response_crc_and_length_match(self):
        packet=avatars.encode_catalog();self.assertEqual(packet[:6],b'\xac\x08'+struct.pack('<I',len(avatars.catalog())))
        for identity,row in avatars.catalog().items():
            blob=avatars.image_packet(identity)
            self.assertEqual(blob[:2],b'\xac\x06')
            self.assertEqual(struct.unpack('<IH',blob[2:8]),(identity,len(blob)-8))
            self.assertLessEqual(len(blob)-8,4096)
            self.assertEqual(zlib.crc32(blob[8:]),row['crc32'])
            self.assertEqual(blob[8:10],b'\xff\xd8')

    def test_generated_portraits_use_ordinary_gallery_and_persist_per_owner(self):
        packet=avatars.encode_catalog()
        records={identity:(category,price,crc) for category,identity,price,crc in struct.iter_unpack('<BIII',packet[6:])}
        generated=[i for i,r in avatars.catalog().items() if r.get('generated')]
        self.assertEqual(generated,list(range(10007,10013)))
        for identity in generated:
            self.assertEqual(records[identity],(0,0,avatars.catalog()[identity]['crc32']))
            avatars.assign(self.path,'alice',1,identity,allowed=True)
            self.assertEqual(avatars.selections(self.path,'alice'),{1:identity})
            self.assertEqual(avatars.selections(self.path,'bob'),{})

    def test_original_requests_assign_owned_human_and_reject_admin_upload_and_extra_data(self):
        wire=b'\xac\x05'+struct.pack('<II',2,10002)
        self.assertEqual(avatars.request(self.path,'alice',wire,allowed=True),(avatars.snapshot(self.path,'alice'),))
        self.assertEqual(avatars.selections(self.path,'alice'),{2:10002})
        for wire in (wire+b'\0',wire[:-1],b'\xac\x03',b'\xac\x09'+bytes(8)):
            with self.assertRaises(ValueError):avatars.request(self.path,'alice',wire,allowed=True)

    def test_woman_all_dog_breeds_and_miner_can_keep_their_portraits(self):
        from tio.protocol.pet_info import PetInfo,SCHEMAS
        from tio.arena_roster import room_soldiers
        base=decode_pet_info(self.store.list('alice')[0][1],human_equipment=True).fields
        wanted={3:10004,4:10005,5:10005,6:10005,7:10006}
        for identity,resource in ((3,2),(4,3),(5,4),(6,5),(7,6)):
            human=resource in (1,2,6)
            fields={**base,'0x8c43eb':identity,'0x8c446f':resource,'0x8c44a6':1}
            schema=SCHEMAS[(human,bool(fields['0x6d0203']),bool(fields['0x8c4565']))]
            fields={key:fields.get(key,0) for key,_,_ in schema}
            self.store.ensure('alice',encode_pet_info(PetInfo(human,fields)),encode_item_list(identity,()),human=human)
            avatars.assign(self.path,'alice',identity,wanted[identity],allowed=True)
            row=next(r for r in self.store.list('alice') if r[0]==identity)
            self.assertEqual(room_soldiers((row,),1,path=self.path,account='alice')[0].avatar_id,wanted[identity])
        packet=avatars.snapshot(self.path,'alice')
        self.assertEqual(dict(struct.unpack_from('<II',packet,n) for n in range(4,len(packet),8)),{1:0,2:0,**wanted})
        self.assertEqual(avatars.selections(self.path,'bob'),{})
        avatars.assign(self.path,'alice',4,0,allowed=True)
        self.assertEqual(avatars.selections(self.path,'alice')[4],0)

    def test_room_metadata_includes_saved_avatar_for_each_owner(self):
        from tio.arena_roster import room_soldiers
        avatars.assign(self.path,'alice',1,10001,allowed=True)
        rows=self.store.list('alice')
        self.assertEqual(room_soldiers(rows,1,path=self.path,account='alice')[0].avatar_id,10001)
        self.assertEqual(room_soldiers(rows,1,path=self.path,account='bob')[0].avatar_id,0)

    def test_battle_assignment_uses_global_actor_ids_and_hides_unseen_opponents(self):
        from tio.battle_state import BattleField,BattleActor
        from tio.battle_item_visuals import packets
        from tio import battle_snapshot
        field=BattleField(32,20,[BattleActor(6,7,2,3,40,200,200,5),BattleActor(9,8,25,12,40,200,200,5)],step_cost=1,teams={7:0,8:1})
        field.avatar_ids={6:10001,9:10003}
        self.assertEqual(packets(field,7)[-1],avatars.encode_assignments(((6,10001),)))
        self.assertEqual(packets(field,8)[-1],avatars.encode_assignments(((9,10003),)))
        restored,_=battle_snapshot.loads(battle_snapshot.dumps(field))
        self.assertEqual(packets(restored,7)[-1],packets(field,7)[-1])

    def test_city_sync_cannot_overwrite_remapped_battle_actors(self):
        import threading
        from types import SimpleNamespace
        from unittest.mock import patch
        from server.avatar_service import sync
        class Session:pass
        session=Session();session.database=self.path;session.account='alice';session.owned_pet_probe=True
        session.router=SimpleNamespace(team_arena=SimpleNamespace(lock=threading.RLock()))
        class Presence:
            lock=threading.RLock()
            messages={session:[]}
        with patch('server.economy_runtime.city_idle',return_value=False):sync(Presence,session)
        self.assertEqual(Presence.messages[session],[])
        with patch('server.economy_runtime.city_idle',return_value=True):sync(Presence,session)
        self.assertEqual(Presence.messages[session],[avatars.snapshot(self.path,'alice')])


if __name__=='__main__':unittest.main()
