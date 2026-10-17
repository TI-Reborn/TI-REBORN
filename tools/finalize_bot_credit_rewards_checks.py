"""Audit deployed sources, service and exact successful/failed QA cleanup."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.verify_bot_credit_rewards_hosted import remote


def main():
    folder=ROOT/'reports/bot-credit-rewards-20261016';names=set();matches=[]
    for mode in ('humans','solo','team','wall'):
        row=json.loads((folder/('hosted-'+mode+'.json')).read_text())
        assert row['passed'] and row['ranking_excluded'] and row['cleanup']['unrelated_rows_preserved']
        names.update(row['fixtures']);matches.append(row['snapshot']['match'])
    for path in folder.glob('failed-hosted-*-1.json'):
        row=json.loads(path.read_text());cleanup=json.loads(path.with_name(path.stem+'-cleanup.json').read_text())
        assert row['ranking_excluded'] and row['cleanup']['unrelated_rows_preserved']
        assert cleanup['passed'] and cleanup['unrelated_rows_preserved']
        names.update(row['fixtures']);matches.append(row['snapshot']['match'])
    code=(ROOT/'tools/verify_bot_credit_rewards_health_remote.py').read_text()
    result=remote(code,dict(qa_names=sorted(names),qa_matches=matches))
    result['audited_qa_matches']=len(matches)
    (folder/'final-health.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result))


if __name__=='__main__':main()
