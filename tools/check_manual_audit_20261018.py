"""Run existing bounded regressions against the read-only hosted source snapshot.

All tests run locally with their own temporary databases; no hosted QA calls.
"""
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT/'work/manual-audit-20261018/hosted'
REPORT = ROOT/'reports/manual-audit-20261018'
GROUPS = {
    'portable-baseline': None,
    'combat': ['test_combat_completion','test_equipment_batch','test_shared_equipment_batch','test_tactical_marks','test_weapon_proficiency','test_weapon_effects','test_dog_abilities','test_miner_abilities'],
    'roster-world': ['test_roster_progression','test_world_completion','test_world_core_integration','test_services_completion','test_services','test_avatars','test_hire'],
    'clans-social': ['test_alliances','test_alliance_service','test_alliance_crests','test_clan_benefits','test_clan_benefits_integration','test_base_fund_completion','test_social_completion','test_achievements','test_achievement_benefits'],
    'trade': ['test_wagers','test_shared_wager_arena','test_private_shops','test_player_auction','test_sc_auction','test_rental','test_shop_completion','test_bank_economy','test_mail','test_mail_service'],
    'mining-ratings': ['test_mine_rounds','test_mine_claims_and_tax','test_shared_mine_arena','test_rating_completion','test_team_ranked','test_ranks','test_crystal_quotes_consistency','test_crystal_quote_history'],
}


def decoded(value):
    return value.decode('utf-8',errors='replace') if isinstance(value,bytes) else value or ''


def main():
    if '--aligned' in sys.argv:
        aligned()
        return
    shutil.copytree(ROOT/'tests', SNAPSHOT/'tests', dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    # Use the current GitHub portable runner, whose source list is explicit.
    runner = ROOT/'work/pr1-review-20261018/git-sync/tools/run_server_checks.py'
    shutil.copy2(runner,SNAPSHOT/'tools/run_server_checks.py')
    result=[]
    for group, modules in GROUPS.items():
        sets=[('baseline',[sys.executable,'-X','utf8','tools/run_server_checks.py'])] if modules is None else [
            (name,[sys.executable,'-X','utf8','-m','unittest','discover','-s','tests','-p',name+'.py','-v'])
            for name in modules if (SNAPSHOT/'tests'/f'{name}.py').is_file()]
        for name,command in sets:
            start=time.monotonic()
            try:
                p=subprocess.run(command,cwd=SNAPSHOT,capture_output=True,encoding='utf-8',timeout=55)
                output=p.stdout+p.stderr;code=p.returncode
            except subprocess.TimeoutExpired as e:
                output=decoded(e.stdout)+decoded(e.stderr);code='timeout'
            (REPORT/f'tests-{name}.log').write_text(output,encoding='utf-8')
            count=re.findall(r'Ran (\d+) tests?',output)
            row=dict(group=group,module=name,exit=code,tests=int(count[-1]) if count else None,seconds=round(time.monotonic()-start,2))
            result.append(row)
            (REPORT/'test-results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
            print(json.dumps(row),flush=True)


def aligned():
    """Separate current portable fixtures from stale historical Gold fixtures."""
    git = ROOT/'work/pr1-review-20261018/git-sync'
    runner=SNAPSHOT/'tools/run_server_checks.py'
    prior_runner=runner.read_bytes()
    runner.write_bytes((git/'tools/run_server_checks.py').read_bytes())
    shutil.copytree(git/'tests',SNAPSHOT/'tests',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copytree(git/'deploy',SNAPSHOT/'deploy',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for name in ('MULTIPLAYER.md','TEAM_LOBBIES.md','CITY_SOCIAL.md','SURVIVAL_MULTIPLAYER.md','requirements.txt','SERVER_AUDIT.md','DEPLOY_HETZNER.md','CLIENT_CONNECTION.md'):
        shutil.copy2(git/name,SNAPSHOT/name)
    names=('test_battle_item_effects','test_shared_battle_items','test_combat_sight_scatter',
           'test_credits_only','test_city_services','test_city_services_integration','test_achievement_completed_items',
           'test_shared_team_arena','test_team_lobbies','test_battle_exchange','test_durability','test_world_reward_integration')
    commands=[('baseline',[sys.executable,'-X','utf8','tools/run_server_checks.py'])]
    commands += [(n,[sys.executable,'-X','utf8','-m','unittest','discover','-s','tests','-p',n+'.py','-v']) for n in names if (SNAPSHOT/'tests'/f'{n}.py').is_file()]
    commands += [('preflight',[sys.executable,'-X','utf8','-m','server','--check'])]
    result=[]
    for name,command in commands:
        start=time.monotonic()
        try:
            p=subprocess.run(command,cwd=SNAPSHOT,capture_output=True,encoding='utf-8',timeout=180 if name=='baseline' else 55)
            output=p.stdout+p.stderr;code=p.returncode
        except subprocess.TimeoutExpired as e:
            output=decoded(e.stdout)+decoded(e.stderr);code='timeout'
        (REPORT/f'aligned-{name}.log').write_text(output,encoding='utf-8')
        count=re.findall(r'Ran (\d+) tests?',output)
        row=dict(module=name,exit=code,tests=int(count[-1]) if count else None,seconds=round(time.monotonic()-start,2))
        result.append(row)
        (REPORT/'aligned-results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(row),flush=True)
    runner.write_bytes(prior_runner)


if __name__ == '__main__':
    main()
