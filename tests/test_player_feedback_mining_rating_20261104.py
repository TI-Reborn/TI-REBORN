"""Mining standings use settled net earnings, never the spendable wallet."""
from contextlib import closing
import sqlite3
import unittest


class MiningRatingTests(unittest.TestCase):
    def setUp(self):
        from test_mine_claims_and_tax import MineClaimAndTaxTests
        self.f = MineClaimAndTaxTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        with closing(sqlite3.connect(self.f.path)) as db, db:
            db.execute('CREATE TABLE accounts(login TEXT PRIMARY KEY)')
            db.executemany('INSERT INTO accounts VALUES (?)',
                           [(n,) for n in ('miner', 'defender', 'raider', 'leader', 'other')])

    def test_shared_tax_and_escort_split_are_counted_once_in_the_right_role(self):
        f = self.f
        claim = f.claim(tax=10)
        report = f.report(101, claim=claim, defender='defender')
        f.settle('pair', **report)
        f.settle('pair', **report)
        with closing(sqlite3.connect(f.path)) as db, db:
            db.execute("UPDATE crystal_wallets SET amount=0")
        self.assertEqual([(r[1], r[2:]) for r in f.market.ratings(1)], [(b'Miner', (50, 1))])
        self.assertEqual([(r[1], r[2:]) for r in f.market.ratings(3)], [(b'Defender', (41, 1))])
        self.assertEqual(f.market.ratings(2), ())

    def test_raider_pair_and_legacy_extractions_survive_restart_and_read_only_queries(self):
        from tio.crystal_market import CrystalMarket
        f = self.f
        report = f.report(101, role=2, extractor='raider', miner=None)
        report['raiders'] = ['raider', 'other']
        f.settle('raid', **report)
        with closing(sqlite3.connect(f.path)) as db, db:
            CrystalMarket.extract(db, 'miner', 'legacy', 37)
        market = CrystalMarket(f.path)
        before = f.path.read_bytes()
        self.assertEqual([(r[1], r[2]) for r in market.ratings(2)], [(b'Other', 51), (b'Raider', 50)])
        self.assertEqual([(r[1], r[2]) for r in market.ratings(1)], [(b'Miner', 37)])
        self.assertEqual(f.path.read_bytes(), before)

    def test_qa_excluded_retired_and_orphan_owners_never_enter_public_standings(self):
        from tio.crystal_market import CrystalMarket
        f = self.f
        with closing(sqlite3.connect(f.path)) as db, db:
            db.execute('CREATE TABLE rating_exclusions(account TEXT PRIMARY KEY)')
            db.execute("INSERT INTO rating_exclusions VALUES ('other')")
            from tio.character_lifecycle import schema, retire
            schema(db)
            retire(db, 'leader', 1, 'leader', 100)
            for owner in ('qs12345678a', 'orphan'):
                if owner != 'orphan':
                    db.execute('INSERT INTO accounts VALUES (?)', (owner,))
                db.execute('INSERT INTO characters VALUES (?,1,?,?)', (owner, owner.encode(), owner))
            for owner in ('miner', 'other', 'leader', 'qs12345678a', 'orphan'):
                CrystalMarket.extract(db, owner, 'old-'+owner, 100)
        self.assertEqual([r[1] for r in f.market.ratings(1)], [b'Miner'])

    def test_menu_uses_literal_native_row_order_and_rejects_invalid_selectors(self):
        from tio.mining_service import MiningService
        from tio.protocol.binary import Reader
        from types import SimpleNamespace
        f = self.f
        f.settle('solo', **f.report(99))
        service = MiningService(f.path, SimpleNamespace(_durable=None), None)
        _, (packet,) = service.handle('miner', 1, b'Miner', b'\xb0\x28\1')
        r = Reader(packet)
        self.assertEqual(r.read(3), b'\xb0\x29\1')
        self.assertEqual(r.u16(), 1)
        self.assertGreater(r.u32(), 0)
        self.assertEqual(r.read(6), b'Miner\0')
        self.assertEqual((r.u32(), r.u16()), (99, 1))
        r.finish()
        for selector in (0, 4, 255):
            with self.assertRaises(ValueError):
                service.handle('miner', 1, b'Miner', bytes((0xb0, 0x28, selector)))
