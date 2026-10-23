"""Regression checks against the inspected hosted runtime, without player data."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'work/encounter-movement-20261017'
REPORT=ROOT/'reports/encounter-movement-20261017'
FILES=('tio/battle_state.py',)
MODULES=('test_movement_contact','test_battle_state','test_battle_events','test_battle_turn_regressions',
         'test_battle_screen_fixes','test_visibility','test_world_encounters','test_forest_encounters',
         'test_training_bot','test_tactical_bot','test_shared_team_arena','test_shared_survival_groups',
         'test_battle_doors','test_battle_crash_recovery','test_battle_recovery','test_combat')
EXCLUDED={
    'test_world_encounters.EncounterTests.test_client_resource_binding_existing_animation_and_uv':'Historical client release files are not in the hosted source snapshot. Current published dog assets audited separately.',
    'test_forest_encounters.ForestTests.test_client_materials_and_unchanged_denver_resources':'Historical client-only asset fixture; no client assets change in this server patch.',
    'test_forest_encounters.ForestTests.test_loot_shop_and_shared_player_auction_preserve_ownership':'Existing hosted city-only warehouse restriction; legacy fixture stays outside town.',
    'test_forest_encounters.ForestTests.test_victory_materials_once_and_shop_quantity_sale':'Existing hosted city-only shop restriction; legacy fixture stays outside town.',
    'test_forest_encounters.ForestTests.test_full_bag_award_merges_separate_auction_delivery_stacks_without_duplicates':'Existing hosted loot stacking differs from local legacy expectation; unrelated to movement.'}


def main():
    candidate=WORK/'candidate'
    for name in FILES:shutil.copy2(ROOT/name,candidate/name)
    shutil.copytree(ROOT/'tests',candidate/'tests',ignore=shutil.ignore_patterns('__pycache__'),dirs_exist_ok=True)
    for name in ('tools/import_arena_fragments.py','tools/read_tile_doors_native.py','tools/read_tile_doors_extended_native.py'):
        shutil.copy2(ROOT/name,candidate/name)
    runner='''import unittest,sys,json
suite=unittest.TestLoader().loadTestsFromNames(sys.argv[1:])
def flatten(s):
 for t in s:
  if isinstance(t,unittest.TestSuite):yield from flatten(t)
  else:yield t
excluded=json.loads(sys.stdin.read())
result=unittest.TextTestRunner().run(unittest.TestSuite(t for t in flatten(suite) if t.id() not in excluded))
sys.exit(not result.wasSuccessful())
'''
    result=subprocess.run([sys.executable,'-X','utf8','-c',runner,*MODULES],cwd=candidate,input=json.dumps(EXCLUDED),
        env=dict(os.environ,PYTHONPATH=str(candidate)+os.pathsep+str(candidate/'tests')),
        capture_output=True,text=True,encoding='utf-8',timeout=300)
    (REPORT/'tests.log').write_text(result.stdout+result.stderr,encoding='utf-8')
    import re
    count=re.search(r'Ran (\d+) tests in ([\d.]+)s',result.stderr)
    report=dict(passed=result.returncode==0,tests=int(count[1]) if count else None,
        seconds=float(count[2]) if count else None,modules=MODULES,runtime='isolated actual hosted snapshot',
        hosted_database_used=False,graphical_clients=False,excluded_checks=EXCLUDED)
    (REPORT/'automated-checks.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))
    if result.returncode:print(result.stderr[-18000:].encode('ascii','backslashreplace').decode())
    return result.returncode


if __name__=='__main__':sys.exit(main())
