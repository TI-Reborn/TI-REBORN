from contextlib import closing
from dataclasses import replace
import sqlite3,struct,unittest
import test_shared_team_arena as shared
from tio.owned_pets import OwnedPetStore
from tio.wallets import WalletStore
from tio.protocol.pet_info import decode_pet_info
from tio.protocol.asset_count import decode_asset_count
from tio.protocol.player_auction import encode_settings
from tio.battle_recovery import CREDITS_PER_HP


class PostBattleTreatmentTests(unittest.TestCase):
    setUp=shared.SharedTeamTests.setUp
    send=shared.SharedTeamTests.send
    create=shared.SharedTeamTests.create
    paired=shared.SharedTeamTests.paired

    def finished(self):
        owners,battle=self.paired();field=battle['field']
        for identity,actor in tuple(field._actors.items()):
            field._actors[identity]=replace(actor,health=30 if actor.owner_id==owners[0] else 0)
        self.hub.finish(battle)
        for q in self.hub.queues.values():q.clear()
        return owners,battle

    def hp(self,index):
        raw=OwnedPetStore(self.path).list(self.sessions[index].account)[0][1]
        fields=decode_pet_info(raw,human_equipment=True).fields
        return fields['0x8c4ab1'],fields['0x8c4a07']

    def credits(self,index):
        return WalletStore(self.path).ensure(self.sessions[index].account).credits

    def request(self,ids):
        return b'\x7c'+bytes((len(ids),))+b''.join(struct.pack('<I',i) for i in ids)

    def test_native_finish_exit_then_heal_remaps_ids_and_is_idempotent(self):
        owners,battle=self.finished();field=battle['field']
        ids=field.actor_ids(owners[0]);before=self.credits(0);other=(self.hp(1),self.credits(1))
        hp,maximum=self.hp(0);cost=(maximum-hp)*CREDITS_PER_HP
        self.assertGreater(ids[0],0x40000000)
        self.send(0,b'\x2a\x01')
        packets=self.send(0,self.request(ids))
        self.assertEqual(self.hp(0),(maximum,maximum));self.assertEqual(self.credits(0),before-cost)
        self.assertEqual(decode_asset_count(packets[0]).credits,before-cost)
        self.assertEqual(decode_pet_info(packets[1],human_equipment=True).fields['0x8c4ab1'],maximum)
        self.send(0,self.request(ids));self.assertEqual(self.credits(0),before-cost)
        self.assertEqual((self.hp(1),self.credits(1)),other)

    def test_heal_while_result_open_and_reload_use_updated_balance_and_health(self):
        owners,battle=self.finished();field=battle['field'];ids=field.actor_ids(owners[1])
        hp,maximum=self.hp(1);before=self.credits(1)
        self.assertEqual(hp,0)
        self.send(1,self.request(ids))
        self.assertEqual(self.credits(1),before-maximum*CREDITS_PER_HP)
        self.assertEqual(field.actor(ids[0]).health,maximum)
        cached=next(p for p in battle['result_packets'][owners[1]] if p[:2]==b'\xc8\x39')
        self.assertEqual(decode_asset_count(cached).credits,self.credits(1))
        self.send(1,b'\x2a\x01');self.send(1,self.request(ids))
        self.assertEqual(self.credits(1),before-maximum*CREDITS_PER_HP)

    def test_unchecked_finish_keeps_wounds_and_money(self):
        owners,battle=self.finished();before=(self.hp(0),self.credits(0))
        self.send(0,b'\x2a\x01');self.assertEqual((self.hp(0),self.credits(0)),before)

    def test_no_money_or_foreign_actor_is_atomic_and_reports_error(self):
        owners,battle=self.finished();field=battle['field'];ids=field.actor_ids(owners[0])
        foreign=field.actor_ids(owners[1])[0]
        self.send(0,b'\x2a\x01');before=(self.hp(0),self.credits(0))
        for requested in ((foreign,),(ids[0],foreign),(ids[0],ids[0])):
            self.assertEqual(self.send(0,self.request(requested))[0][0],0xf0)
            self.assertEqual((self.hp(0),self.credits(0)),before)
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('UPDATE wallets SET credits=1 WHERE account=?',(self.sessions[0].account,))
        self.assertEqual(self.send(0,self.request(ids))[0][0],0xf0)
        self.assertEqual(self.hp(0),before[0]);self.assertEqual(self.credits(0),1)

    def test_treatment_during_active_battle_is_rejected(self):
        owners,battle=self.paired();ids=battle['field'].actor_ids(owners[0])
        self.hub.queues[owners[0]].clear();before=(self.hp(0),self.credits(0))
        packets=self.send(0,self.request(ids))
        self.assertTrue(any(p[0]==0xf0 for p in packets))
        self.assertEqual((self.hp(0),self.credits(0)),before)

    def test_tariff_in_settings_matches_charge_policy(self):
        self.assertEqual(struct.unpack('<f',encode_settings(1800000000)[2:6])[0],CREDITS_PER_HP)
        for value in (0,-1,float('nan'),float('inf')):
            with self.assertRaises(ValueError):encode_settings(1800000000,heal_price=value)

    def test_previous_result_mapping_cannot_heal_during_new_search(self):
        from unittest.mock import patch
        owners,battle=self.finished();ids=battle['field'].actor_ids(owners[0])
        self.send(0,b'\x2a\x01');before=(self.hp(0),self.credits(0))
        with patch.object(self.sessions[0].survival,'searching',return_value=True):
            self.assertEqual(self.send(0,self.request(ids))[0][0],0xf0)
        self.assertEqual((self.hp(0),self.credits(0)),before)


class TreatmentTCPTests(unittest.TestCase):
    def test_two_accounts_finish_then_treat_in_one_write(self):
        import test_multi_account as tcp
        from tio.protocol.arena import ArenaCreateRequest,encode_create_request
        from tio.protocol.transport import encode_initial_frame
        from tio.protocol.system_message import encode_current_town
        case=tcp.MultiAccountTests();case.setUp();self.addCleanup(case.doCleanups);case.start()
        peers=[]
        for account,name in (('alice','Alice'),('bob','Bob')):
            peer=case.handoff(case.begin(account));case.enter(peer,name);peers.append(peer)
            peer.send(encode_create_request(ArenaCreateRequest(1,0,4,2,40,1,1,0,0)))
            peer.until(b'\x25');peer.send(b'\x2e')
        for peer in peers:peer.until(b'\x41',max_packets=512)
        hub=case.server.multi.team_arena
        with hub.lock:
            sessions=[case.server.multi.active_accounts[n] for n in ('alice','bob')]
            owners=[hub.identities[s] for s in sessions];battle=hub.battles[owners[0]]
            field=battle['field'];identity=field.actor_ids(owners[1])[0]
            for i,actor in tuple(field._actors.items()):
                field._actors[i]=replace(actor,health=0 if field.teams[actor.owner_id]==1 else actor.health)
            hub.finish(battle)
        for peer in peers:peer.until(b'\x4c',max_packets=512)
        store=OwnedPetStore(case.config.database);wallet=WalletStore(case.config.database)
        before=wallet.ensure('bob').credits
        saved=decode_pet_info(store.list('bob')[0][1],human_equipment=True)
        maximum=saved.fields['0x8c4a07'];self.assertEqual(saved.fields['0x8c4ab1'],0)
        other=(store.list('alice'),wallet.ensure('alice'))
        request=b'\x7c\x01'+struct.pack('<I',identity);peer=peers[1]
        peer.sock.sendall(encode_initial_frame(b'\x2a\x01',peer.outbound)+encode_initial_frame(request,peer.outbound))
        peer.until(encode_current_town(3),max_packets=512)
        assets=decode_asset_count(peer.until(b'\xc8\x39',max_packets=512))
        pet=decode_pet_info(peer.until(b'\x66',max_packets=512),human_equipment=True)
        self.assertEqual(pet.fields['0x8c4ab1'],maximum)
        self.assertEqual(assets.credits,before-maximum*CREDITS_PER_HP)
        peer.send(request);peer.until(b'\xc8\x39');peer.until(b'\x66')
        self.assertEqual(wallet.ensure('bob').credits,assets.credits)
        self.assertEqual((store.list('alice'),wallet.ensure('alice')),other)
        peers[0].send(b'\x2a\x01');case.ping(peers[0])
