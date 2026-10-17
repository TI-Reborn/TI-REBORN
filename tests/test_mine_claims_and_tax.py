from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from contextlib import redirect_stdout,redirect_stderr
from io import StringIO
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest

from tio.clans import (ClansStore,ClanRejected,DEFAULT_RIGHTS,WITHDRAW_CRYSTALS,
                       CRYSTAL_MONEY_ID,project_inventory)
from tio.crystal_market import CrystalMarket
from tio.db_transaction import connect
from tio.mine_claims import MineClaimsStore,MineClaimRejected
from tio.owned_pets import OwnedPetStore
from tio.protocol.item_list import decode_item_list,encode_item_list
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.warehouse import decode_warehouse_list
from tio.protocol.warehouse_transfer import WarehouseTransfer,encode_warehouse_transfer
from tio.wallets import WalletStore
from tio.warehouse_service import transfer_private_items


class MineClaimAndTaxTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.path=Path(folder.name)/'mines.sqlite3'
        trial=json.loads((Path(__file__).resolve().parents[1]/'evidence/owned_pet_trial.json').read_text())
        pet=decode_pet_info(bytes.fromhex(trial['packet_hex']),human_equipment=True)
        pet.fields['0x8c4aef']=4
        self.pets=OwnedPetStore(self.path)
        for account in ('miner','defender','raider','leader','other'):
            self.pets.ensure(account,encode_pet_info(pet),encode_item_list(1,()),human=True)
            WalletStore(self.path).ensure(account)
        with closing(connect(self.path)) as db,db:
            db.execute('CREATE TABLE characters(account TEXT,slot INTEGER,name BLOB,name_key TEXT UNIQUE)')
            db.executemany('INSERT INTO characters VALUES (?,1,?,?)',[(a,a.title().encode(),a) for a in ('miner','defender','raider','leader','other')])
        self.clans=ClansStore(self.path)
        self.cid=self.clans.create('leader',b'Mine Owners')
        self.clans.invite('leader',b'Defender');self.clans.accept('defender',1)
        self.other=self.clans.create('other',b'Other Clan')
        self.market=CrystalMarket(self.path)
        self.claims=MineClaimsStore(self.path,clock=lambda:123)

    def claim(self,location=13,tax=10,owner=None):
        previous=self.claims.freeze(location)
        return self.claims.admin_set_claim(location,self.cid if owner is None else owner,
            tax_percent=tax,expected_revision=previous['revision'],actor='operator:test',reason='local fixture only')

    def report(self,gross,*,role=1,extractor='miner',claim=None,miner='miner',defender=None):
        return dict(gross=gross,role=role,extractor=extractor,claim=claim or self.claims.freeze(13),miner=miner,defender=defender)

    def settle(self,match='match',**report):
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE')
            return CrystalMarket.settle_mine(db,match,**report)

    def snapshot(self):
        with closing(connect(self.path)) as db:
            return {t:db.execute('SELECT * FROM '+t+' ORDER BY 1,2').fetchall() for t in
                    ('crystal_wallets','clan_crystals','crystal_extractions','mine_crystal_extractions','clan_ledger','clans')}

    def test_no_implicit_owner_and_explicit_durable_operator_claim(self):
        self.assertEqual(self.claims.freeze(13),dict(location=13,owner_clan=None,tax_percent=0,revision=0))
        with self.assertRaises(MineClaimRejected):self.claims.authorize_defender('defender',self.claims.freeze(13))
        claim=self.claim()
        self.assertEqual(claim,dict(location=13,owner_clan=self.cid,tax_percent=10,revision=1))
        self.assertEqual(MineClaimsStore(self.path).freeze(13),claim)
        with closing(connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT actor,reason,created FROM mine_claim_history').fetchone(),
                             ('operator:test','local fixture only',123))
        for changes in (dict(owner_clan=99999),dict(tax_percent=11),dict(expected_revision=0),dict(actor=''),dict(location=3)):
            args=dict(location=13,owner_clan=self.cid,tax_percent=10,expected_revision=1,actor='op',reason='test');args.update(changes)
            with self.assertRaises(MineClaimRejected):self.claims.admin_set_claim(**args)
        self.assertEqual(self.claims.freeze(13),claim)

    def test_operator_changes_block_active_checkpoint_and_pending_outbox(self):
        from tio.battle_checkpoints import schema as checkpoints
        from tio.battle_settlement import schema as outbox
        with closing(connect(self.path)) as db,db:
            checkpoints(db);outbox(db)
            db.execute("INSERT INTO battle_checkpoints VALUES ('battle',1,'{}','checksum',0,'active',NULL)")
        with self.assertRaises(MineClaimRejected):self.claim()
        with closing(connect(self.path)) as db,db:
            db.execute('DELETE FROM battle_checkpoints')
            db.execute("INSERT INTO battle_settlement_jobs(match_id,account,payload) VALUES ('battle','miner','{}')")
        with self.assertRaises(MineClaimRejected):self.claim()
        with closing(connect(self.path)) as db,db:db.execute('DELETE FROM battle_settlement_jobs')
        self.claim()

    def test_defense_requires_current_owner_clan_at_admission(self):
        claim=self.claim()
        self.assertEqual(self.claims.authorize_defender('defender',claim),self.cid)
        for account in ('miner','raider','other'):
            with self.assertRaises(MineClaimRejected):self.claims.authorize_defender(account,claim)
        self.clans.remove('defender')
        with self.assertRaises(MineClaimRejected):self.claims.authorize_defender('defender',claim)
        # Admission was already legitimately frozen: settlement does not revoke
        # an earned share because a member left after joining the battle.
        receipt=self.settle(**self.report(100,claim=claim,defender='defender'))
        self.assertEqual(receipt['payouts'],dict(miner=50,defender=40))

    def test_unowned_miner_and_raider_keep_every_crystal_no_defender(self):
        for match,role,account,miner in (('mining',1,'miner','miner'),('raid',2,'raider',None)):
            receipt=self.settle(match,**self.report(1000,role=role,extractor=account,miner=miner))
            self.assertEqual((receipt['tax'],receipt['payouts']),(0,{account:1000}))
        before=self.snapshot()
        with self.assertRaises(ValueError):self.settle('bad-defense',**self.report(100,defender='defender'))
        self.assertEqual(self.snapshot(),before)

    def test_solo_tax_integer_rounding_and_replay_receipt(self):
        claim=self.claim(14)
        report=self.report(1011,claim=claim)
        receipt=self.settle(**report)
        self.assertEqual((receipt['gross'],receipt['tax'],receipt['payouts']),(1011,101,dict(miner=910)))
        before=self.snapshot()
        self.assertEqual(self.settle(**report),receipt)
        self.assertEqual(self.snapshot(),before)
        with closing(connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT operation FROM clan_ledger WHERE operation='mine_tax'").fetchall(),[('mine_tax',)])

    def test_first_escort_exit_ends_mission_and_conserves_actual_gross(self):
        claim=self.claim()
        first=self.settle(**self.report(101,claim=claim,defender='defender'))
        before=self.snapshot()
        with self.assertRaises(ValueError):self.settle(**self.report(203,role=3,extractor='defender',claim=claim,defender='defender'))
        self.assertEqual(self.snapshot(),before)
        self.assertEqual(first['payouts'],dict(miner=50,defender=41))
        self.assertEqual((self.market.balance('miner'),self.market.balance('defender'),self.clans.info('leader')['crystals']),(50,41,10))
        self.assertEqual(sum(first['payouts'].values())+first['tax'],101)

    def test_raider_tax_exempt_even_with_owned_checkpoint_and_escort(self):
        receipt=self.settle(**self.report(1000,role=2,extractor='raider',claim=self.claim(),defender='defender'))
        self.assertEqual((receipt['tax'],receipt['payouts']),(0,dict(raider=1000)))
        self.assertEqual(self.clans.info('leader')['crystals'],0)
        self.assertEqual(self.market.balance('defender'),0)

    def test_frozen_claim_stays_original_owner_and_rate(self):
        frozen=self.claim()
        self.claim(tax=0,owner=self.other)
        receipt=self.settle(**self.report(100,claim=frozen))
        self.assertEqual((receipt['owner_clan'],receipt['tax']),(self.cid,10))
        self.assertEqual(self.clans.info('leader')['crystals'],10)
        self.assertEqual(self.clans.info('other')['crystals'],0)

    def test_forged_history_and_missing_owner_fail_without_payments(self):
        claim=self.claim();before=self.snapshot()
        forged=dict(claim,tax_percent=0)
        with self.assertRaises(MineClaimRejected):self.settle(**self.report(100,claim=forged))
        self.assertEqual(self.snapshot(),before)
        with closing(connect(self.path)) as db,db:db.execute('DELETE FROM clans WHERE id=?',(self.cid,))
        before=self.snapshot()
        with self.assertRaises(MineClaimRejected):self.settle(**self.report(100,claim=claim))
        self.assertEqual(self.snapshot(),before)

    def test_exact_replay_survives_owner_removal_conflict_cannot_change_receipt(self):
        report=self.report(100,claim=self.claim(),defender='defender');receipt=self.settle(**report)
        with closing(connect(self.path)) as db,db:db.execute('DELETE FROM clans WHERE id=?',(self.cid,))
        before=self.snapshot()
        self.assertEqual(self.settle(**report),receipt)
        for changes in (dict(gross=101),dict(defender=None),dict(role=2),dict(claim=dict(report['claim'],tax_percent=0))):
            with self.assertRaises(ValueError):self.settle(**dict(report,**changes))
        self.assertEqual(self.snapshot(),before)

    def test_match_capacity_and_same_frozen_checkpoint_prevent_double_drill(self):
        frozen=self.claim();self.settle(**self.report(750,claim=frozen))
        before=self.snapshot()
        with self.assertRaises(ValueError):self.settle(**self.report(251,role=2,extractor='raider',miner=None,claim=frozen))
        with self.assertRaises(ValueError):self.settle(**self.report(250,role=2,extractor='raider',miner=None,claim=self.claim(14)))
        # claim configuration and its operator audit are separate from payout state.
        self.assertEqual(self.snapshot(),before)
        with self.assertRaises(ValueError):self.settle(**self.report(250,role=2,extractor='raider',miner=None,claim=frozen))
        self.assertEqual(self.market.balance('raider'),0)

    def test_two_frozen_raiders_share_without_tax_and_replay_once(self):
        values=self.report(101,role=2,extractor='raider',miner=None,claim=self.claim())
        values['raiders']=['raider','defender']
        receipt=self.settle(**values)
        self.assertEqual(receipt['payouts'],dict(raider=50,defender=51))
        self.assertEqual(receipt['tax'],0)
        before=self.snapshot();self.assertEqual(self.settle(**values),receipt);self.assertEqual(self.snapshot(),before)

    def test_recipient_and_clan_cap_overflow_roll_back_every_part(self):
        frozen=self.claim()
        for table,key,account in (('crystal_wallets','account','miner'),('crystal_wallets','account','defender'),('clan_crystals','clan_id',self.cid)):
            with closing(connect(self.path)) as db,db:
                db.execute('INSERT OR REPLACE INTO '+table+' VALUES (?,4294967295)',(account,))
            before=self.snapshot()
            with self.assertRaises(ValueError):self.settle(**self.report(100,claim=frozen,defender='defender'))
            self.assertEqual(self.snapshot(),before)
            with closing(connect(self.path)) as db,db:db.execute('DELETE FROM '+table+' WHERE '+key+'=?',(account,))

    def test_audit_failure_rolls_back_all_balances_and_receipts(self):
        frozen=self.claim()
        with closing(connect(self.path)) as db,db:
            db.execute("CREATE TRIGGER failed_tax BEFORE INSERT ON clan_ledger WHEN NEW.operation='mine_tax' BEGIN SELECT RAISE(ABORT,'test'); END")
        before=self.snapshot()
        with self.assertRaises(sqlite3.IntegrityError):self.settle(**self.report(100,claim=frozen,defender='defender'))
        self.assertEqual(self.snapshot(),before)

    def test_legacy_and_shared_receipts_cannot_pay_the_same_extraction_twice(self):
        report=self.report(100,claim=self.claim());self.settle(**report);before=self.snapshot()
        with closing(connect(self.path)) as db,db:
            CrystalMarket.extract(db,'miner','match',100)
            with self.assertRaises(ValueError):CrystalMarket.extract(db,'raider','match',100)
        self.assertEqual(self.snapshot(),before)
        with closing(connect(self.path)) as db,db:CrystalMarket.extract(db,'miner','old-match',100)
        before=self.snapshot()
        with self.assertRaises(ValueError):self.settle('old-match',**report)
        self.assertEqual(self.snapshot(),before)

    def test_concurrent_exact_replay_and_competing_capacity_are_serialized(self):
        report=self.report(750,claim=self.claim())
        with ThreadPoolExecutor(max_workers=2) as pool:
            receipts=list(pool.map(lambda _:self.settle(**report),range(2)))
        self.assertEqual(receipts[0],receipts[1]);self.assertEqual(self.market.balance('miner'),675)
        reports=[self.report(600,claim=report['claim']),self.report(600,role=2,extractor='raider',miner=None,claim=report['claim'])]
        def attempt(report):
            try:self.settle('competing',**report);return True
            except ValueError:return False
        with ThreadPoolExecutor(max_workers=2) as pool:self.assertEqual(sorted(pool.map(attempt,reports)),[False,True])

    def test_dissolution_preserves_owned_checkpoint_and_tax_property(self):
        self.clans.remove('defender');frozen=self.claim()
        with self.assertRaises(ClanRejected):self.clans.dissolve('leader',self.cid)
        self.settle(**self.report(100,claim=frozen))
        self.claims.admin_set_claim(13,None,tax_percent=0,expected_revision=1,actor='operator',reason='explicit release')
        with self.assertRaises(ClanRejected):self.clans.dissolve('leader',self.cid)
        self.clans.exchange('leader',1,2,withdrawals=((CRYSTAL_MONEY_ID,10),))
        self.clans.dissolve('leader',self.cid)
        self.assertIsNone(self.clans.info('leader'))
        self.assertEqual(self.market.balance('leader'),10)

    def test_tax_is_native_safe_currency_with_rights_and_can_be_sold(self):
        claim=self.claim(16)
        for i in range(4):self.settle('tax'+str(i),**self.report(3000,claim=claim))
        entries=decode_warehouse_list(self.clans.warehouse_packets('defender',2)[0])[3]
        self.assertEqual([(i.instance_id,i.template_id,i.count) for i in entries],[(CRYSTAL_MONEY_ID,51,1200)])
        packet=encode_warehouse_transfer(WarehouseTransfer(2,1,(),((CRYSTAL_MONEY_ID,1000),)))
        with self.assertRaises(ClanRejected):transfer_private_items(self.path,'defender',packet,capacity=32)
        self.clans.permissions('leader',self.clans.info('defender')['member_id'],DEFAULT_RIGHTS|WITHDRAW_CRYSTALS,0)
        replies=transfer_private_items(self.path,'defender',packet,capacity=32)
        self.assertEqual((self.market.balance('defender'),self.clans.info('leader')['crystals']),(1000,200))
        projection=project_inventory(self.path,'defender',replies[0])
        crystals=[i for i in decode_item_list(projection)[1] if i.template_id==51]
        self.assertEqual([(i.instance_id,i.count) for i in crystals],[(CRYSTAL_MONEY_ID,1000)])
        self.assertFalse(any(i.template_id==51 for i in decode_item_list(self.pets.inventory('defender',1))[1]))
        credits=WalletStore(self.path).ensure('defender').credits
        self.assertEqual(self.market.sell('defender',1000),1000)
        self.assertEqual((self.market.balance('defender'),WalletStore(self.path).ensure('defender').credits),(0,credits+1000))

    def test_extraction_requires_outer_transaction(self):
        with closing(connect(self.path)) as db:
            with self.assertRaises(ValueError):CrystalMarket.settle_mine(db,'match',**self.report(1))

    def test_crystal_safe_caps_cross_clan_and_audit_failure_preserve_balances(self):
        self.settle(**self.report(100,claim=self.claim()))
        self.clans.permissions('leader',self.clans.info('defender')['member_id'],DEFAULT_RIGHTS|WITHDRAW_CRYSTALS,0)
        before=self.snapshot()
        with self.assertRaises(ClanRejected):self.clans.exchange('other',1,2,withdrawals=((CRYSTAL_MONEY_ID,1),))
        self.assertEqual(self.snapshot(),before)
        with closing(connect(self.path)) as db,db:db.execute("INSERT INTO crystal_wallets VALUES ('defender',4294967295)")
        before=self.snapshot()
        with self.assertRaises(ClanRejected):self.clans.exchange('defender',1,2,withdrawals=((CRYSTAL_MONEY_ID,1),))
        self.assertEqual(self.snapshot(),before)
        with closing(connect(self.path)) as db,db:
            db.execute('UPDATE clan_crystals SET amount=4294967295 WHERE clan_id=?',(self.cid,))
        before=self.snapshot()
        with self.assertRaises(ClanRejected):self.clans.exchange('defender',1,2,deposits=((CRYSTAL_MONEY_ID,1),))
        self.assertEqual(self.snapshot(),before)
        with closing(connect(self.path)) as db,db:
            db.execute("DELETE FROM crystal_wallets WHERE account='defender'")
            db.execute('UPDATE clan_crystals SET amount=10 WHERE clan_id=?',(self.cid,))
            db.execute("CREATE TRIGGER failed_safe BEFORE INSERT ON clan_ledger WHEN NEW.operation='money' BEGIN SELECT RAISE(ABORT,'test'); END")
        before=self.snapshot();inventory=self.pets.inventory('defender',1)
        with self.assertRaises(sqlite3.IntegrityError):self.clans.exchange('defender',1,2,withdrawals=((CRYSTAL_MONEY_ID,1),))
        self.assertEqual(self.snapshot(),before);self.assertEqual(self.pets.inventory('defender',1),inventory)

    def test_concurrent_crystal_safe_withdrawals_cannot_duplicate_tax(self):
        with closing(connect(self.path)) as db,db:db.execute('INSERT INTO clan_crystals VALUES (?,1000)',(self.cid,))
        self.clans.permissions('leader',self.clans.info('defender')['member_id'],DEFAULT_RIGHTS|WITHDRAW_CRYSTALS,0)
        def take(account):
            try:self.clans.exchange(account,1,2,withdrawals=((CRYSTAL_MONEY_ID,800),));return True
            except ClanRejected:return False
        with ThreadPoolExecutor(max_workers=2) as pool:self.assertEqual(sorted(pool.map(take,('leader','defender'))),[False,True])
        self.assertEqual(self.clans.info('leader')['crystals'],200)
        self.assertEqual(sum(self.market.balance(a) for a in ('leader','defender')),800)

    def test_operator_cli_reads_and_changes_only_explicit_claim_configuration(self):
        from tools.manage_mine_claims import main
        args=['--db',str(self.path)]
        before=self.snapshot()
        with redirect_stdout(StringIO()) as output:main(args+['show','13'])
        self.assertEqual(json.loads(output.getvalue()),[dict(location=13,owner_clan=None,tax_percent=0,revision=0)])
        self.assertEqual(self.snapshot(),before)
        with redirect_stdout(StringIO()) as output:
            main(args+['set','13','--clan',str(self.cid),'--expected-revision','0','--actor','operator','--reason','fixture'])
        self.assertEqual(json.loads(output.getvalue())['owner_clan'],self.cid)
        self.assertEqual(self.snapshot(),before)
        with redirect_stderr(StringIO()),self.assertRaises(SystemExit) as failure:
            main(args+['set','13','--clan',str(self.cid),'--expected-revision','0','--actor','operator','--reason','stale'])
        self.assertEqual(failure.exception.code,2)
        with redirect_stdout(StringIO()) as output:
            main(args+['clear','13','--expected-revision','1','--actor','operator','--reason','release'])
        self.assertIsNone(json.loads(output.getvalue())['owner_clan'])


if __name__=='__main__':unittest.main()
