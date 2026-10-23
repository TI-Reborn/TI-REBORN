"""Verify the targeted recovery candidate against actual hosted sources."""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'work/recovery-roster-20261017'
REPORT=ROOT/'reports/recovery-roster-20261017'
FILES=('tio/battle_recovery.py','tools/loopback_exchange.py')
MODULES=('test_recovery_roster_updates','test_battle_recovery','test_health_protocol',
         'test_passive_stats','test_equipment_bonuses','test_ranks','test_owned_pets',
         'test_ability_learning','test_battle_crash_recovery')


def main():
    candidate=WORK/'candidate'
    shutil.copy2(ROOT/'tio/battle_recovery.py',candidate/'tio/battle_recovery.py')
    shutil.copytree(ROOT/'tests',candidate/'tests',ignore=shutil.ignore_patterns('__pycache__'),dirs_exist_ok=True)
    before=(WORK/'baseline/tools/loopback_exchange.py').read_text(encoding='utf-8')
    expected=before.replace('from tio.battle_recovery import decode_treatment,treat\n','from tio.battle_recovery import decode_treatment,treat_updates\n')
    expected=expected.replace('assets,cost=treat(self.database,self.account,decode_treatment(packet),blocked=blocked)\n                            roster=OwnedPetStore(self.database).list(self.account)\n                            replies=(encode_asset_count(assets),*(p for _,p,_ in roster))',
                            'assets,cost,health=treat_updates(self.database,self.account,decode_treatment(packet),blocked=blocked)\n                            replies=(encode_asset_count(assets),*health)')
    expected=expected.replace('    def achievement_delivery_ready(self,character):',
        '    def recovery_blocked(self,character):\n        """City recovery must not send local pet IDs into a shared battle."""\n        return (any(character in room.members for room in self.arena.rooms.snapshot())\n                or bool(self.router and self.router.team_arena.busy(self)))\n\n    def achievement_delivery_ready(self,character):')
    expected=expected.replace("            if hasattr(self,'recovery'):\n                blocked=any(character in room.members for room in self.arena.rooms.snapshot())",
                              "            if hasattr(self,'recovery'):\n                blocked=self.recovery_blocked(character)")
    assert expected!=before and expected==(candidate/'tools/loopback_exchange.py').read_text(encoding='utf-8'),'Unexpected adapter changes'
    result=subprocess.run([sys.executable,'-X','utf8','-m','unittest',*MODULES],cwd=candidate,
        env=dict(os.environ,PYTHONPATH=str(candidate)+os.pathsep+str(candidate/'tests')),
        capture_output=True,text=True,encoding='utf-8',timeout=180)
    (REPORT/'tests.log').write_text(result.stdout+result.stderr,encoding='utf-8')
    count=re.search(r'Ran (\d+) tests in ([\d.]+)s',result.stderr)
    report=dict(passed=result.returncode==0,tests=int(count[1]) if count else None,seconds=float(count[2]) if count else None,
                modules=MODULES,actual_hosted_source_snapshot=True,hosted_player_database_used=False,
                graphical_clients=False,hosted_update_applied=False)
    (REPORT/'automated-checks.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
    if result.returncode:
        print(result.stderr[-10000:].encode('ascii','backslashreplace').decode());return result.returncode
    manifest={name:dict(before=hashlib.sha256((WORK/'baseline'/name).read_bytes()).hexdigest(),
                       after=hashlib.sha256((candidate/name).read_bytes()).hexdigest()) for name in FILES}
    (REPORT/'patch-manifest.json').write_text(json.dumps(manifest,indent=2))
    archive=WORK/'recovery-roster-patch.tar.gz'
    with tarfile.open(archive,'w:gz') as out:
        for name in FILES:out.add(candidate/name,arcname=name)
        raw=json.dumps(manifest).encode();entry=tarfile.TarInfo('manifest.json');entry.size=len(raw);out.addfile(entry,io.BytesIO(raw))
    package=dict(archive=str(archive),sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),files=FILES,
                 tested_source='actual hosted snapshot with only the targeted recovery changes',
                 hosted_update_applied=False,player_data_included=False)
    (REPORT/'package.json').write_text(json.dumps(package,indent=2));print(json.dumps(package))
    return 0


if __name__=='__main__':sys.exit(main())
