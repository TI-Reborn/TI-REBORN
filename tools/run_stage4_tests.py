"""Capture the full backend suite with source hashes and a bounded runtime."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / 'reports/stage4-economy'
FILES = ('tio/wallets.py','tio/battle_rewards.py','tio/reward_policy.py',
         'tio/ranks.py','config/level_progression.json','tio/level_progression.py',
         'server/team_arena.py','tools/loopback_exchange.py')


def main():
    log = FOLDER/'full-tests.log'
    result = FOLDER/'full-tests.json'
    if log.exists() or result.exists():
        raise RuntimeError('Full suite results already exist')
    hashes = {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in FILES}
    began = datetime.now(timezone.utc).isoformat()
    start = time.monotonic()
    with log.open('xb') as output:
        completed = subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-v'],
                                   cwd=ROOT,stdout=output,stderr=subprocess.STDOUT,timeout=1500)
    content = log.read_text(encoding='utf-8',errors='replace')
    count = re.search(r'Ran (\d+) tests?',content)
    skipped = re.search(r'skipped=(\d+)',content)
    report = dict(started_utc=began,finished_utc=datetime.now(timezone.utc).isoformat(),
                  elapsed_seconds=round(time.monotonic()-start,2),exit_code=completed.returncode,
                  passed=completed.returncode==0,test_count=int(count[1]) if count else None,
                  skipped=int(skipped[1]) if skipped else 0,source_sha256=hashes,
                  source_unchanged=all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==value for name,value in hashes.items()))
    result.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))
    return completed.returncode if report['source_unchanged'] else 1


if __name__=='__main__':raise SystemExit(main())
