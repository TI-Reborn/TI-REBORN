"""Capture the full suite against the shared-mines candidate without replacing prior evidence."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'reports/shared-mines'
FILES=('tio/mining.py','tio/mine_map.py','tio/clans.py','tio/crystal_market.py',
       'tio/mine_claims.py','tio/protocol/mining.py','tio/arena_service.py',
       'tio/battle_rewards.py','tools/mining_scene.py','tools/manage_mine_claims.py',
       'server/mine_arena.py','server/team_arena.py','server/battle_journal.py',
       'server/battle_reconnect.py','server/battle_events.py')

def main():
    FOLDER.mkdir(parents=True,exist_ok=True)
    suffix=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    log=FOLDER/('full-tests-'+suffix+'.log')
    result=log.with_suffix('.json')
    hashes={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in FILES}
    began=datetime.now(timezone.utc).isoformat();start=time.monotonic()
    with log.open('xb') as output:
        completed=subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-v'],
            cwd=ROOT,stdout=output,stderr=subprocess.STDOUT,timeout=1500)
    content=log.read_text(encoding='utf-8',errors='replace')
    count=re.search(r'Ran (\d+) tests?',content);skipped=re.search(r'skipped=(\d+)',content)
    report=dict(started_utc=began,finished_utc=datetime.now(timezone.utc).isoformat(),
        elapsed_seconds=round(time.monotonic()-start,2),exit_code=completed.returncode,
        passed=completed.returncode==0,test_count=int(count[1]) if count else None,
        skipped=int(skipped[1]) if skipped else 0,source_sha256=hashes,
        source_unchanged=all(hashlib.sha256((ROOT/n).read_bytes()).hexdigest()==h for n,h in hashes.items()))
    result.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(report=str(result),**report)))
    return completed.returncode if report['source_unchanged'] else 1

if __name__=='__main__':raise SystemExit(main())
