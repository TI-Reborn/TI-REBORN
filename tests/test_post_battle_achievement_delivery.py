"""City delivery after retained result bookkeeping, including real TCP frames."""
from contextlib import closing
from dataclasses import replace
import sqlite3
import struct
from types import SimpleNamespace
import unittest

from tio.achievements import AchievementStore,update
from tio.battle_recovery import CREDITS_PER_HP
from tio.owned_pets import OwnedPetStore
from tio.protocol.arena import ArenaCreateRequest,encode_create_request
from tio.protocol.asset_count import decode_asset_count
from tio.protocol.pet_info import decode_pet_info
from tio.protocol.system_message import encode_current_town
from tio.protocol.transport import encode_initial_frame
from tio.wallets import WalletStore
from tio.warehouse import WarehouseStore
from tools.loopback_exchange import LoopbackExchange


class RetainedCityAchievementTests(unittest.TestCase):
    def fixture(self):
        from test_shared_team_arena import SharedTeamTests
        case=SharedTeamTests();case.setUp();self.addCleanup(case.doCleanups)
        session=case.sessions[0];session.router=SimpleNamespace(team_arena=case.hub)
        session._achievement_city_confirmed=True
        session.arena._completed.add(session.probe_character_id)
        return case,session

    def ready(self,session):
        return LoopbackExchange.achievement_delivery_ready(session,session.probe_character_id)

    def assert_pending_then_once(self,case,session,earned_credits=100):
        store=AchievementStore(case.path)
        with closing(sqlite3.connect(case.path)) as db,db:update(db,session.account,add={'shop_purchase':1})
        before=WalletStore(case.path).ensure(session.account).credits
        self.assertFalse(self.ready(session))
        self.assertEqual(WalletStore(case.path).ensure(session.account).credits,before)
        # The full TCP test below verifies the real C2S50 confirmation sets
        # this flag; here isolate its reset across each real room lifecycle.
        session._achievement_city_confirmed=True
        self.assertTrue(self.ready(session));replies=store.flush(session.account)
        self.assertTrue(any(p[:2]==b'\xb5\x03' for p in replies))
        self.assertEqual(WalletStore(case.path).ensure(session.account).credits,before+earned_credits)
        self.assertEqual(store.flush(session.account),())
        self.assertIn(session.probe_character_id,session.arena._completed)

    def test_private_lobby_resets_old_city_confirmation_and_retained_result_waits(self):
        case,session=self.fixture();self.assertTrue(self.ready(session))
        session.arena.rooms.create(session.probe_character_id,ArenaCreateRequest(0,0,2,2,40,1,1,0,0))
        self.assertFalse(self.ready(session));self.assertFalse(session._achievement_city_confirmed)
        session.arena.rooms.leave(session.probe_character_id)
        session.arena._completed.add(session.probe_character_id)
        self.assert_pending_then_once(case,session)

    def test_shared_lobby_battle_result_reset_confirmation_and_finish_keeps_treatment_ids(self):
        case,session=self.fixture();self.assertTrue(self.ready(session))
        case.create(0);self.assertFalse(self.ready(session));self.assertFalse(session._achievement_city_confirmed)
        case.send(0,b'\x2e');case.create(1);case.send(1,b'\x2e')
        owner=case.hub.identities[session];battle=case.hub.battles[owner]
        self.assertFalse(self.ready(session))
        for identity,actor in tuple(battle['field']._actors.items()):
            if battle['field'].side(actor.owner_id)!=battle['field'].side(owner):
                battle['field']._actors[identity]=replace(actor,health=0)
        case.hub.finish(battle);self.assertFalse(self.ready(session))
        case.send(0,b'\x2a\x01');self.assertFalse(case.hub.busy(session))
        self.assertTrue(session._battle_treatment_ids)
        self.assert_pending_then_once(case,session,earned_credits=350)


class AchievementCityTCPTests(unittest.TestCase):
    def test_finish_city_confirmation_delivers_pending_items_and_money_once_without_relogin(self):
        from test_multi_account import MultiAccountTests
        case=MultiAccountTests();case.setUp();self.addCleanup(case.doCleanups);case.start()
        peers=[]
        for account,name in (('alice','Alice'),('bob','Bob')):
            peer=case.handoff(case.begin(account));case.enter(peer,name);peers.append(peer)
            peer.send(b'\x50\x03');case.ping(peer)
            peer.send(encode_create_request(ArenaCreateRequest(1,0,4,2,40,1,1,0,0)))
            peer.until(b'\x25');peer.send(b'\x2e')
        for peer in peers:peer.until(b'\x41',max_packets=512)
        hub=case.server.multi.team_arena
        with hub.lock:
            session=case.server.multi.active_accounts['alice'];other=case.server.multi.active_accounts['bob']
            owner=hub.identities[session];battle=hub.battles[owner];field=battle['field']
            identity=field.actor_ids(owner)[0]
            self.assertFalse(session._achievement_city_confirmed)
            # Fixtures create pending prizes only after the city was left.
            with closing(sqlite3.connect(case.config.database)) as db,db:
                update(db,'alice',add={'kills':10,'shop_purchase':1})
            for i,actor in tuple(field._actors.items()):
                field._actors[i]=replace(actor,health=30 if field.side(actor.owner_id)==field.side(owner) else 0)
            hub.finish(battle)
        for peer in peers:peer.until(b'\x4c',max_packets=512)
        wallet=WalletStore(case.config.database);before=wallet.ensure('alice').credits
        other_before=wallet.ensure('bob')
        self.assertFalse(WarehouseStore(case.config.database).items('alice'))
        peer=peers[0];peer.send(b'\x2a\x01');peer.until(encode_current_town(3),max_packets=512)
        self.assertIn(session.probe_character_id,session.arena._completed)
        self.assertTrue(session._battle_treatment_ids)
        # An unrelated town packet cannot unlock city-only economic delivery.
        peer.send(b'\x50\x04');case.ping(peer)
        self.assertFalse(session._achievement_city_confirmed)
        self.assertEqual(wallet.ensure('alice').credits,before)
        peer.send(b'\x50\x03')
        peer.until(b'\xb5\x03',max_packets=512)
        assets=decode_asset_count(peer.until(b'\xc8\x39',max_packets=512))
        # A clean team win grants250 and the first shop purchase grants100.
        self.assertEqual(assets.credits,before+350)
        self.assertEqual(wallet.ensure('alice').credits,before+350)
        items=WarehouseStore(case.config.database).items('alice')
        self.assertEqual(sorted(i.template_id for i in items),[10,10,317,317,317])
        self.assertEqual(wallet.ensure('bob'),other_before)
        self.assertFalse(hub.busy(session));self.assertTrue(hub.busy(other))
        # Confirming the city does not discard the late native shared ID map.
        saved=decode_pet_info(OwnedPetStore(case.config.database).list('alice')[0][1],human_equipment=True)
        cost=(saved.fields['0x8c4a07']-saved.fields['0x8c4ab1'])*CREDITS_PER_HP
        request=b'\x7c\x01'+struct.pack('<I',identity)
        peer.send(request)
        healed=decode_asset_count(peer.until(b'\xc8\x39',max_packets=512))
        pet=decode_pet_info(peer.until(b'\x66',max_packets=512),human_equipment=True)
        self.assertEqual(healed.credits,assets.credits-cost)
        self.assertEqual(pet.fields['0x8c4ab1'],pet.fields['0x8c4a07'])
        # Repeat Finish, town confirmation and treatment preserve prize receipts.
        peer.sock.sendall(encode_initial_frame(b'\x2a\x01',peer.outbound)+
                          encode_initial_frame(b'\x50\x03',peer.outbound)+
                          encode_initial_frame(request,peer.outbound))
        case.ping(peer)
        self.assertEqual(wallet.ensure('alice').credits,healed.credits)
        self.assertEqual(WarehouseStore(case.config.database).items('alice'),items)
        with closing(sqlite3.connect(case.config.database)) as db:
            self.assertEqual(db.execute('SELECT delivered FROM achievement_prizes WHERE account=? AND id IN (4,31,38)',
                                        ('alice',)).fetchall(),[(1,),(1,),(1,),(1,)])
        peers[1].send(b'\x2a\x01');case.ping(peers[1])


if __name__=='__main__':unittest.main()
