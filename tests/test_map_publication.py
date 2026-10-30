import copy
import unittest
from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile

from tools.publish_global_map_v3_remote import transition


class MapPublicationTests(unittest.TestCase):
    def test_deployer_rollback_command_runs_against_a_real_database(self):
        from tio.locations import LocationStore, center
        from tools.deploy_game_operations_remote import MAP_ROLLBACK_SOURCE
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'rollback.db'
            LocationStore(path)
            with closing(sqlite3.connect(path)) as db,db:
                LocationStore._save(db,'alice',3,*center(3))
            result = subprocess.run([sys.executable,'-c',MAP_ROLLBACK_SOURCE,str(path)],
                                    capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('SELECT x,y FROM character_locations').fetchone(),(-154,-318))

    def manifests(self):
        old = dict(schema=1,version='2026.10.28.2',files=[
            dict(path=n,size=1,sha256='a'*64,seed=False) for n in ('silver.dll','ti.exe')])
        new = copy.deepcopy(old); new['version']='2026.10.29.1'
        new['files'][0]['sha256']='b'*64
        new['files'] += [dict(path=f'base/pda/global-map-v3/{i}.png',size=1,sha256=f'{i:064x}')
                         for i in range(75)]
        return old,new

    def test_map_update_preserves_unrelated_client_files(self):
        old,new = self.manifests()
        self.assertEqual(len(transition(old,new)),76)
        new['files'][1]['sha256']='c'*64
        with self.assertRaises(ValueError):
            transition(old,new)

    def test_unsafe_added_path_is_rejected(self):
        old,new = self.manifests(); new['files'][-1]['path']='base/pda/global-map-v3/../../x.png'
        with self.assertRaises(ValueError):
            transition(old,new)
