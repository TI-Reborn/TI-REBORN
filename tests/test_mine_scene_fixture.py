import tempfile
import unittest
import hashlib
import json
from pathlib import Path
from tools.mine_scene_fixture import without_deposits,hidden_static_deposits
from tools.import_mine_maps import read


class MineSceneFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.target=self.base/'maps/mines_01/mine_03.s'
        self.target.parent.mkdir(parents=True)
        self.original=Path(r'C:\Program Files (x86)\TIOnline\base\maps\mines_01\mine_03.s').read_bytes()
        # An open game has this scene temporarily patched by the launcher.
        # Use its verified original backup without altering the running game.
        root=Path(__file__).resolve().parents[1]
        source=next(m for m in json.loads((root/'config/mine_maps.json').read_text()) if m['file']=='mine_03')
        if hashlib.sha256(self.original).hexdigest()!=source['sha256']:
            backup=(root/'data/session-backups'/('mine_03-original-'+source['sha256']+'.s')).read_bytes()
            self.assertEqual(hashlib.sha256(backup).hexdigest(),source['sha256'])
            self.assertEqual(without_deposits(backup),self.original)
            self.original=backup
        self.target.write_bytes(self.original)
        self.backups=self.base/'backups'

    def test_only_authored_deposit_removed_and_source_restored(self):
        before=read(self.target)
        with hidden_static_deposits(self.base,self.backups):
            after=read(self.target)
            self.assertEqual(after['tiles'],before['tiles'])
            self.assertEqual(after['models'],[m for m in before['models'] if m[0]!='mine_heyser.t'])
            self.assertEqual(len(after['models']),len(before['models'])-1)
            self.assertEqual(without_deposits(self.target.read_bytes()),self.target.read_bytes())
        self.assertEqual(self.target.read_bytes(),self.original)

    def test_interrupted_run_recovery_and_unknown_file_protection(self):
        with self.assertRaises(RuntimeError):
            with hidden_static_deposits(self.base,self.backups):raise RuntimeError('session failed')
        self.assertEqual(self.target.read_bytes(),self.original)
        self.target.write_bytes(without_deposits(self.original))
        with hidden_static_deposits(self.base,self.backups):pass
        self.assertEqual(self.target.read_bytes(),self.original)
        self.target.write_bytes(b'foreign scene')
        with self.assertRaises(ValueError):
            with hidden_static_deposits(self.base,self.backups):pass
        self.assertEqual(self.target.read_bytes(),b'foreign scene')
