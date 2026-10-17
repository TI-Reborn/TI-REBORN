import contextlib
import io
import runpy
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

class ReservationLauncherTests(unittest.TestCase):
    def launch(self, *args):
        with patch('sys.argv', ['run_reservation.py', *args]), patch('subprocess.call', return_value=0) as call:
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as result:
                runpy.run_path(str(ROOT / 'tools/run_reservation.py'), run_name='__main__')
            return result.exception.code, call.call_args

    def test_default_loads_roster_without_automatic_mutations(self):
        code, call = self.launch('--seconds', '6')
        self.assertEqual(code, 0)
        command = call.args[0]
        self.assertIn('--owned-pet-probe', command)
        for flag in ('--hire-probe', '--dismiss-probe', '--shop-purchase-probe', '--shop-sale-probe'):
            self.assertNotIn(flag, command)

    def test_empty_roster_is_explicit_and_rejects_mutation(self):
        code, call = self.launch('--empty-roster')
        self.assertEqual(code, 0)
        self.assertNotIn('--owned-pet-probe', call.args[0])
        code, call = self.launch('--empty-roster', '--probe-hire', '--database', 'test.sqlite3')
        self.assertEqual(code, 2)
        self.assertIsNone(call)

    def test_mutation_probes_cannot_use_main_database(self):
        for flag in ('--probe-hire', '--probe-dismiss', '--probe-purchase', '--probe-sale'):
            code, call = self.launch(flag)
            self.assertEqual(code, 2)
            self.assertIsNone(call)

    def test_battle_settings_probe_requires_isolation(self):
        code,call=self.launch('--probe-battle-members')
        self.assertEqual(code,2)
        self.assertIsNone(call)
        code,call=self.launch('--probe-battle-members','--database','trial.sqlite3','--seconds','6')
        self.assertEqual(code,0)
        self.assertIn('--battle-members-probe',call.args[0])
        self.assertIn('--battle-settings-probe',call.args[0])

    def test_scene_probe_requires_separate_database_and_excludes_mutations(self):
        code,call=self.launch('--probe-battle-actor')
        self.assertEqual(code,2)
        self.assertIsNone(call)
        code,call=self.launch('--probe-battle-actor','--database','actor-trial.sqlite3')
        self.assertEqual(code,0)
        self.assertIn('--battle-actor-probe',call.args[0])
        self.assertIn('--battle-scene-probe',call.args[0])
        for args in ((),('--empty-roster',),('--probe-arena-leave',),('--probe-hire',)):
            extra=('--database','scene-trial.sqlite3') if args else ()
            code,call=self.launch('--probe-battle-scene',*args,*extra)
            self.assertEqual(code,2)
            self.assertIsNone(call)
        code,call=self.launch('--probe-battle-scene','--database','scene-trial.sqlite3')
        self.assertEqual(code,0)
        self.assertIn('--battle-scene-probe',call.args[0])
        self.assertIn('--arena-create-probe',call.args[0])

    def test_arena_create_probe_requires_isolation_and_no_canned_replies(self):
        code,call=self.launch('--probe-arena-leave')
        self.assertEqual(code,2)
        self.assertIsNone(call)
        code,call=self.launch('--probe-arena-leave','--database','trial.sqlite3')
        self.assertEqual(code,0)
        self.assertIn('--arena-leave-probe',call.args[0])
        code,call=self.launch('--probe-arena-ready')
        self.assertEqual(code,2)
        self.assertIsNone(call)
        code,call=self.launch('--probe-arena-ready','--database','trial.sqlite3')
        self.assertEqual(code,0)
        self.assertIn('--arena-ready-probe',call.args[0])
        self.assertIn('--arena-create-probe',call.args[0])
        for args in (('--probe-arena-create',), ('--probe-arena-create','--probe-battle-members','--database','trial.sqlite3'), ('--probe-arena-create','--empty-roster','--database','trial.sqlite3')):
            code,call=self.launch(*args)
            self.assertEqual(code,2)
            self.assertIsNone(call)
        code,call=self.launch('--probe-arena-create','--database','trial.sqlite3','--seconds','8')
        self.assertEqual(code,0)
        self.assertIn('--arena-create-probe',call.args[0])
        self.assertNotIn('--battle-settings-probe',call.args[0])
        for args in (('--probe-battle-settings',),('--probe-battle-settings','--empty-roster','--database','trial.sqlite3'),('--probe-battle-settings','--probe-hire','--database','trial.sqlite3')):
            code,call=self.launch(*args)
            self.assertEqual(code,2)
            self.assertIsNone(call)
        code,call=self.launch('--probe-battle-settings','--database','trial.sqlite3','--seconds','6')
        self.assertEqual(code,0)
        self.assertIn('--battle-settings-probe',call.args[0])
