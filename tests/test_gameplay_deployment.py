"""Game deployment remains code-only and guards hosted source/data boundaries."""
import ast
import unittest
from tools.deploy_gameplay_completion import valid_path,validate,program,pristine_sc_catalog


class GameplayDeploymentTests(unittest.TestCase):
    def test_system_catalogue_exception_rejects_every_player_bid_and_changed_prize(self):
        import sqlite3,tempfile
        from contextlib import closing
        from pathlib import Path
        from tio.sc_auction import SCAuctionStore
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'players.sqlite3';store=SCAuctionStore(path)
            store.tick(now=100)
            with closing(sqlite3.connect(path)) as db,db:
                pristine_sc_catalog(db,store.rules)
            store.tick(now=10000)
            with closing(sqlite3.connect(path)) as db,db:
                pristine_sc_catalog(db,store.rules)
                db.execute("UPDATE sc_auction_lots SET bidder='alice' WHERE id=1")
                with self.assertRaises(RuntimeError):pristine_sc_catalog(db,store.rules)
                db.execute('UPDATE sc_auction_lots SET bidder=NULL,item_packet=? WHERE id=1',(b'changed',))
                with self.assertRaises(RuntimeError):pristine_sc_catalog(db,store.rules)
                db.rollback()
                db.execute("INSERT INTO sc_auction_history(lot,account,action,amount,occurred) VALUES (1,'alice','bid',5,10001)")
                with self.assertRaises(RuntimeError):pristine_sc_catalog(db,store.rules)

    def test_rejects_player_data_absolute_paths_traversal_and_wrong_formats(self):
        for path in ('','/opt/tio-emulator/tio/combat.py','C:/TIO-emulator/config/a.json',
                     'tio/../../players.py','server\\a.py','reports/a.py','config/data.sqlite3',
                     'config/nested/a.json','evidence/new.xml','var/lib/tio-server/reservation.sqlite3'):
            with self.subTest(path=path):self.assertFalse(valid_path(path))
        for path in ('tio/protocol/wagers.py','server/wager_arena.py','config/wagers.json','tools/survival_scene.py'):
            self.assertTrue(valid_path(path))

    def test_candidate_formats_are_parsed_before_any_remote_call(self):
        for path,raw in (('tio/a.py',b'bad ! python'),('config/a.json',b'{'),
                         ('evidence/items_diagnostic.xml',b'<!DOCTYPE x><x/>'),
                         ('evidence/items_diagnostic.xml',b'<x>')):
            with self.subTest(path=path),self.assertRaises((SyntaxError,ValueError,Exception)):
                validate(path,raw)
        validate('tio/a.py',b'a=1\n');validate('config/a.json',b'{}')
        validate('evidence/items_diagnostic.xml',b'<root/>')

    def test_adapted_remote_program_keeps_idle_checks_and_never_restores_database(self):
        code=program(('tio/protocol/wagers.py','config/wagers.json'))
        ast.parse(code)
        self.assertIn("source.backup(destination)",code)
        self.assertIn("backup/'previous-code-config.tar.gz'",code)
        self.assertIn("before=fingerprint(dbpath)",code)
        self.assertIn("if fingerprint(backup/'reservation.sqlite3')!=before",code)
        self.assertIn("all_existing_tables_unchanged",code)
        self.assertIn("New active game/battle state prevents safe code rollback",code)
        self.assertNotIn("str(complete)",code)
        self.assertNotIn("shutil.copy2(backup/'reservation.sqlite3'",code)
        self.assertNotIn("destination.backup(source)",code)
        allowed=next(n.value for n in ast.walk(ast.parse(code)) if isinstance(n,ast.Assign)
                     and any(isinstance(t,ast.Name) and t.id=='allowed' for t in n.targets))
        self.assertEqual(ast.literal_eval(allowed.args[0]),['config/wagers.json','tio/protocol/wagers.py'])


if __name__=='__main__':unittest.main()
