from contextlib import closing
from dataclasses import replace
import sqlite3,struct,unittest
import test_shared_team_arena as shared
from tio.owned_pets import OwnedPetStore
from tio.wallets import WalletStore
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
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
        self.assertEqual(struct.unpack('<f',encode_settings(1800000000,heal_price=0)[2:6])[0],0)
        for value in (-1,float('nan'),float('inf')):
            with self.assertRaises(ValueError):encode_settings(1800000000,heal_price=value)

    def test_previous_result_mapping_cannot_heal_during_new_search(self):
        from unittest.mock import patch
        owners,battle=self.finished();ids=battle['field'].actor_ids(owners[0])
        self.send(0,b'\x2a\x01');before=(self.hp(0),self.credits(0))
        with patch.object(self.sessions[0].survival,'searching',return_value=True):
            self.assertEqual(self.send(0,self.request(ids))[0][0],0xf0)
        self.assertEqual((self.hp(0),self.credits(0)),before)


class TreatmentTCPTests(unittest.TestCase):
    def test_two_accounts_treat_mixed_squads_by_each_fighters_level(self):
        import test_multi_account as tcp
        from tio.protocol.arena import ArenaCreateRequest,encode_create_request
        from tio.protocol.transport import encode_initial_frame
        from tio.protocol.system_message import encode_current_town
        from tio.protocol.item_list import encode_item_list
        from tio.level_progression import FLOORS,LEVEL,XP
        case=tcp.MultiAccountTests();case.setUp();self.addCleanup(case.doCleanups);case.start()
        store=OwnedPetStore(case.config.database);wallet=WalletStore(case.config.database)
        peers=[];settings=[]
        for account,name in (('alice','Alice'),('bob','Bob')):
            peer=case.handoff(case.begin(account));peers.append(peer)
            receive=peer.receive
            def capture(receive=receive, account=account):
                packet=receive()
                if packet[:2]==b'\xc8\x37':settings.append((account,struct.unpack('<f',packet[2:6])[0]))
                return packet
            peer.receive=capture
            case.enter(peer,name)
            pet=decode_pet_info(store.list(account)[0][1],human_equipment=True)
            recruit=replace(pet,fields={**pet.fields,'0x8c43eb':2,'0x8c44a6':2})
            store.ensure(account,encode_pet_info(recruit),encode_item_list(2,()),human=True)
            peer.send(encode_create_request(ArenaCreateRequest(1,0,4,2,40,2,2,0,0)))
            peer.until(b'\x25');peer.send(b'\x2e')
        for peer in peers:peer.until(b'\x41',max_packets=512)
        self.assertCountEqual(settings,[('alice',0),('bob',0)])
        hub=case.server.multi.team_arena
        with hub.lock:
            sessions=[case.server.multi.active_accounts[n] for n in ('alice','bob')]
            owners=[hub.identities[s] for s in sessions];battle=hub.battles[owners[0]]
            self.assertEqual(battle['city_id'],3)
            field=battle['field'];requests=[]
            for session,owner,paid_id in zip(sessions,owners,(2,1)):
                ids=field.actor_ids(owner)
                self.assertEqual({field.combat.storage_ids[i] for i in ids},{1,2})
                requests.append(b'\x7c\x02'+struct.pack('<II',*ids))
                for identity in ids:
                    local=field.combat.storage_ids[identity]
                    actor=field.actor(identity)
                    field._actors[identity]=replace(actor,health=0 if paid_id==1 else actor.max_health-10)
                    level=3 if local==paid_id else 2
                    xp=FLOORS[3]-1 if local==paid_id else FLOORS[level-1]
                    raw=store.list(session.account)[local-1][1]
                    saved=decode_pet_info(raw,human_equipment=True)
                    packet=encode_pet_info(replace(saved,fields={**saved.fields,LEVEL:level,XP:xp}))
                    with closing(sqlite3.connect(case.config.database)) as db,db:
                        db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=?',
                                   (packet,session.account,local))
                    if local==paid_id:field.combat.experience.totals[identity]=1
            reserve=replace(pet,fields={**pet.fields,'0x8c43eb':3,'0x8c44a6':0,LEVEL:4,'0x8c4ab1':0})
            store.ensure('alice',encode_pet_info(reserve),encode_item_list(3,()),human=True)
            hub.finish(battle)
        for peer in peers:peer.until(b'\x4c',max_packets=512)
        for account,other,peer,request,paid_id in zip(('alice','bob'),('bob','alice'),peers,requests,(2,1)):
            with self.subTest(account=account):
                before=wallet.ensure(account).credits
                other_before=(store.list(other),wallet.ensure(other))
                roster={i:decode_pet_info(p,human_equipment=True).fields for i,p,_ in store.list(account) if i in (1,2)}
                self.assertEqual({i:f[LEVEL] for i,f in roster.items()},{paid_id:4,3-paid_id:2})
                missing={i:f['0x8c4a07']-f['0x8c4ab1'] for i,f in roster.items()}
                self.assertTrue(all(hp>0 for hp in missing.values()))
                cost=missing[paid_id]*CREDITS_PER_HP
                rate=next(rate for owner,rate in reversed(settings) if owner==account)
                self.assertEqual(round(sum(missing.values())*rate),cost)
                peer.sock.sendall(encode_initial_frame(b'\x2a\x01',peer.outbound)+encode_initial_frame(request,peer.outbound))
                peer.until(encode_current_town(3),max_packets=512)
                assets=decode_asset_count(peer.until(b'\xc8\x39',max_packets=512))
                self.assertEqual(assets.credits,before-cost)
                for _ in roster:peer.until(b'\x66',max_packets=512)
                for i,packet,_ in store.list(account):
                    fields=decode_pet_info(packet,human_equipment=True).fields
                    self.assertEqual(fields['0x8c4ab1'],0 if i==3 else fields['0x8c4a07'])
                peer.send(request)
                self.assertEqual(decode_asset_count(peer.until(b'\xc8\x39',max_packets=512)).credits,assets.credits)
                self.assertEqual((store.list(other),wallet.ensure(other)),other_before)
