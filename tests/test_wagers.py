from dataclasses import replace
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from tio.db_transaction import transaction
from tio.protocol.arena import ArenaCreateRequest
from tio.protocol.binary import PacketError
from tio.protocol.wagers import decode_join, decode_kick, decode_transfer
from tio.protocol.wagers import WagerRoomRecord,encode_room_list,decode_room_list
from tio.wallets import WalletStore
from tio import wagers


def request(mode=0, players=2, soldiers=1, stake=100, delta=0):
    return ArenaCreateRequest(mode,2,players,2,20*soldiers+20,soldiers,soldiers,delta,stake)


def admission(accounts=('alice','bob'), sides=None):
    sides = list(range(len(accounts))) if sides is None else sides
    return tuple((a,s,(1,),(3,)) for a,s in zip(accounts,sides))


class WagerStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)/'server.db'
        wallet = WalletStore(self.path)
        for name in ('alice','bob','carol','dave','eve','fred'):
            wallet.ensure(name)
        self.store = wagers.WagerStore(self.path)

    def balances(self):
        with closing(sqlite3.connect(self.path)) as db:
            return dict(db.execute('SELECT account,credits FROM wallets'))

    def reserve(self, match='m', req=None, members=None):
        with transaction(self.path) as db:
            return wagers.reserve(db,match,req or request(),members or admission(),creator_level=3,pool='starter',now=10)

    def active(self):
        with transaction(self.path) as db:
            wagers.transition(db,'m','loading'); wagers.transition(db,'m','active')

    def test_credit_only_atomic_hold_duplicate_and_win_receipts(self):
        self.assertEqual(self.reserve(),200)
        self.assertEqual(self.reserve(),200)
        self.assertEqual(self.balances()['alice'],2900)
        self.active()
        report=dict(version=1,winner_side=0,refund_reason=None)
        with transaction(self.path) as db:
            paid=wagers.settle(db,'m',report)
        self.assertEqual(paid,{'alice':('win',200),'bob':('lose',0)})
        with transaction(self.path) as db:
            self.assertEqual(wagers.settle(db,'m',report),paid)
            self.assertFalse(list(db.execute('SELECT * FROM wager_leases')))
            self.assertEqual(list(db.execute('SELECT DISTINCT gold FROM wallets')),[(0,)])
        self.assertEqual(self.balances()['alice'],3100)
        self.assertEqual(self.balances()['bob'],2900)

    def test_one_underfunded_account_rolls_back_every_account(self):
        with transaction(self.path) as db: db.execute("UPDATE wallets SET credits=99 WHERE account='bob'")
        before=self.balances()
        with self.assertRaises(ValueError): self.reserve()
        self.assertEqual(self.balances(),before)
        with closing(sqlite3.connect(self.path)) as db: self.assertEqual(list(db.execute('SELECT * FROM wager_matches')),[])

    def test_outcome_conflict_and_stale_reservation_rejected(self):
        self.reserve(); self.active()
        with transaction(self.path) as db: wagers.refund(db,'m','draw')
        with self.assertRaises(ValueError): self.reserve()
        with self.assertRaises(ValueError), transaction(self.path) as db:
            wagers.settle(db,'m',dict(version=1,winner_side=0,refund_reason=None))
        self.assertEqual(self.balances()['alice'],3000)

    def test_duplicate_account_cross_match_and_changed_squad_rejected(self):
        with self.assertRaises(ValueError): self.reserve(members=admission(('alice','alice')))
        self.reserve()
        with self.assertRaises(ValueError): self.reserve(match='other')
        with self.assertRaises(ValueError): self.reserve(req=request(stake=99))
        with self.assertRaises(ValueError): self.reserve(members=tuple((a,s,(2,),ls) for a,s,_,ls in admission()))
        self.assertEqual(self.balances()['alice'],2900)

    def test_loading_failure_refunds_and_persists_across_store_restart(self):
        self.reserve()
        with transaction(self.path) as db: wagers.transition(db,'m','loading')
        self.assertEqual(wagers.WagerStore(self.path).recover(()),('m',))
        self.assertEqual(wagers.WagerStore(self.path).recover(()),())
        self.assertEqual(self.balances()['alice'],3000)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT kind,amount FROM wager_receipts WHERE account='bob'").fetchone(),('refund',100))

    def test_process_crash_preserves_active_journaled_and_quarantined_pots(self):
        self.reserve(); self.active()
        self.assertEqual(self.store.recover(('m',)),())
        self.assertEqual(self.balances()['bob'],2900)
        self.assertEqual(self.store.recover(()),('m',))
        self.assertEqual(self.balances()['bob'],3000)

    def test_graceful_stop_refunds_only_held_startup(self):
        self.reserve(); self.reserve('next',members=admission(('carol','dave')))
        self.active()
        self.assertEqual(self.store.stop_unstarted(),('next',))
        self.assertEqual(self.balances()['carol'],3000)
        self.assertEqual(self.balances()['alice'],2900)

    def test_team_pool_split_remainder_and_forfeited_member_excluded(self):
        names=('alice','bob','carol','dave','eve','fred')
        self.reserve(req=request(1,6,stake=101),members=admission(names,(0,0,0,1,1,1)))
        self.active()
        with transaction(self.path) as db:
            wagers.forfeit(db,'m','carol')
            paid=wagers.settle(db,'m',dict(version=1,winner_side=0,refund_reason=None))
        self.assertEqual(paid['alice'],('win',303))
        self.assertEqual(paid['bob'],('win',303))
        self.assertEqual(paid['carol'],('lose',0))
        self.assertEqual(sum(n for _,n in paid.values()),606)

    def test_living_player_needs_all_loaded_before_winning(self):
        self.reserve()
        with self.assertRaises(ValueError), transaction(self.path) as db:
            wagers.settle(db,'m',dict(version=1,winner_side=0,refund_reason=None))
        self.assertEqual(self.balances()['alice'],2900)

    def test_draw_returns_every_stake_even_forfeited_players(self):
        self.reserve(); self.active()
        with transaction(self.path) as db:
            wagers.forfeit(db,'m','bob')
            paid=wagers.settle(db,'m',dict(version=1,winner_side=None,refund_reason='draw'))
        self.assertEqual(paid,{'alice':('refund',100),'bob':('refund',100)})

    def test_terminal_payout_and_gameplay_snapshot_share_one_rollback(self):
        self.reserve(); self.active(); before=self.balances()
        with self.assertRaises(RuntimeError), transaction(self.path) as db:
            wagers.settle(db,'m',dict(version=1,winner_side=0,refund_reason=None))
            raise RuntimeError('checkpoint write failed')
        self.assertEqual(self.balances(),before)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT status FROM wager_matches').fetchone(),('active',))
            self.assertEqual(list(db.execute('SELECT * FROM wager_receipts')),[])

    def test_payout_overflow_is_atomic_and_keeps_pot_for_repair(self):
        self.reserve(); self.active()
        with transaction(self.path) as db: db.execute("UPDATE wallets SET credits=4294967290 WHERE account='alice'")
        before=self.balances()
        with self.assertRaises(ValueError), transaction(self.path) as db:
            wagers.settle(db,'m',dict(version=1,winner_side=0,refund_reason=None))
        self.assertEqual(self.balances(),before)
        with closing(sqlite3.connect(self.path)) as db: self.assertEqual(db.execute('SELECT COUNT(*) FROM wager_leases').fetchone(),(2,))

    def test_level_delta_admission_and_no_gold_stakes(self):
        req=request(delta=2)
        self.reserve(req=req,members=(('alice',0,(1,),(1,)),('bob',1,(1,),(5,))))
        with self.assertRaises(ValueError): self.reserve('other',req,members=(('carol',0,(1,),(6,)),('dave',1,(1,),(3,))))
        for bad in (request(stake=0),request(stake=0xffffffff),request(delta=3),replace(request(),players_count=8)):
            with self.subTest(bad=bad),self.assertRaises(ValueError): wagers.validate_request(bad)


class WagerLobbyTests(unittest.TestCase):
    def setUp(self):
        self.now=0; self.lobbies=wagers.WagerLobbies(clock=lambda:self.now)

    def test_full_real_roster_readiness_transfer_and_departure(self):
        room=self.lobbies.create(10,'alice',request(1,4),3,'starter')
        for owner,name in ((20,'bob'),(30,'carol'),(40,'dave')):
            self.lobbies.join(room.identity,owner,name,(3,),1,'starter')
        self.assertEqual(room.sides,{10:0,20:1,30:0,40:1})
        for owner in (20,30,40):self.lobbies.ready(owner,True)
        self.assertIs(self.lobbies.validate_start(10),room)
        self.lobbies.transfer(10,30,1)
        self.assertEqual(room.ready,set())
        for owner in (20,30,40):self.lobbies.ready(owner,True)
        with self.assertRaises(ValueError):self.lobbies.validate_start(10)
        with self.assertRaises(ValueError):self.lobbies.transfer(20,30,0)
        self.lobbies.leave(10,20)
        self.assertIsNone(self.lobbies.room(20))
        self.assertEqual(self.lobbies.leave(10),(10,30,40))
        self.assertFalse(self.lobbies.rooms)

    def test_account_duplicates_and_levels_are_checked_without_filling_bots(self):
        room=self.lobbies.create(10,'alice',request(0,3,delta=1),3,'starter')
        with self.assertRaises(ValueError):self.lobbies.join(room.identity,20,'alice',(3,),1,'starter')
        with self.assertRaises(ValueError):self.lobbies.join(room.identity,20,'bob',(5,),1,'starter')
        self.lobbies.join(room.identity,20,'bob',(4,),1,'starter')
        self.lobbies.ready(20,True)
        with self.assertRaises(ValueError):self.lobbies.validate_start(10)
        self.lobbies.join(room.identity,30,'carol',(2,),1,'starter')
        self.assertEqual(room.sides,{10:0,20:1,30:2})
        for owner in (20,30):self.lobbies.ready(owner,True)
        self.assertIs(self.lobbies.validate_start(10),room)
        self.lobbies.leave(20)
        self.assertEqual(room.sides,{10:0,30:1})

    def test_countdown_prevents_new_members_and_team_changes(self):
        room=self.lobbies.create(10,'alice',request(1,4),3,'starter')
        room.starts_at=5
        with self.assertRaises(ValueError):self.lobbies.join(room.identity,20,'bob',(3,),1,'starter')
        with self.assertRaises(ValueError):self.lobbies.transfer(10,10,1)


class NativeWagerRequestTests(unittest.TestCase):
    def test_typed_list_uses_u16_name_and_original_record_layout(self):
        room=WagerRoomRecord(42,b'Alice',3,0,3,1,0,2,2,1,0,100)
        packet=encode_room_list((room,))
        self.assertEqual(packet[:6],bytes.fromhex('c82c01000000'))
        self.assertEqual(packet[6:17],bytes.fromhex('2a0000000500416c696365'))
        self.assertEqual(decode_room_list(packet),(room,))
        self.assertEqual(decode_room_list(encode_room_list(())),())
        for n in range(len(packet)):
            with self.subTest(n=n),self.assertRaises(PacketError):decode_room_list(packet[:n])
        with self.assertRaises(PacketError):decode_room_list(packet[:-1]+b'\1')

    def test_pinned_original_builder_bytes(self):
        self.assertEqual(decode_join(bytes.fromhex('292a000000')),42)
        self.assertEqual(decode_kick(bytes.fromhex('2b78563412')),0x12345678)
        self.assertEqual(decode_transfer(bytes.fromhex('2d2a00000001')),(42,1))
        for packet,decoder in ((bytes.fromhex('292a000000'),decode_join),
                (bytes.fromhex('2b78563412'),decode_kick),(bytes.fromhex('2d2a00000001'),decode_transfer)):
            for n in range(len(packet)):
                with self.subTest(packet=packet,n=n),self.assertRaises(PacketError):decoder(packet[:n])
            with self.assertRaises(PacketError):decoder(packet+b'\x00')
        with self.assertRaises(PacketError):decode_transfer(bytes.fromhex('2d2a000000ff'))


if __name__=='__main__':unittest.main()

