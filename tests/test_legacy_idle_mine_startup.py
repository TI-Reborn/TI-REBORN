"""Actual runtime startup with synthetic idle Mine13 saves, no network/data copy."""
from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest

from server.multi import MultiServer


def fingerprint(path):
    with closing(sqlite3.connect(path)) as db:
        tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {name:hashlib.sha256('\n'.join(sorted(repr(tuple(r)) for r in db.execute('SELECT * FROM '+name))).encode()).hexdigest() for name in tables}


class IdleMineStartupTests(unittest.TestCase):
    def test_full_second_startup_keeps_idle_mine_history_and_terrain_uncreated(self):
        with tempfile.TemporaryDirectory(prefix='tio-synthetic-idle-mine-') as folder:
            database=Path(folder)/'synthetic.sqlite3'
            server=SimpleNamespace(config=SimpleNamespace(database=database,
                tls=SimpleNamespace(enabled=False),contracts_enabled=False))
            first=MultiServer(server)
            from tio.locations import LocationStore
            from tio.crystal_market import CrystalMarket
            LocationStore(database);CrystalMarket(database,clock=lambda:1000)
            with closing(sqlite3.connect(database)) as db,db:
                db.execute("INSERT INTO character_locations(account,town_id,x,y) VALUES ('synthetic-idle-miner',13,-170,-274)")
                db.execute("INSERT INTO crystal_wallets VALUES ('synthetic-idle-miner',1250)")
                db.execute("INSERT INTO crystal_extractions VALUES ('historic-mine','synthetic-idle-miner',1250)")
            before=fingerprint(database)
            second=MultiServer(server)
            self.assertEqual(fingerprint(database),before)
            self.assertEqual(first.team_arena.battles,{})
            self.assertEqual(second.team_arena.battles,{})
            self.assertEqual(second.team_arena.mine_instances(13),())


if __name__=='__main__':unittest.main()
