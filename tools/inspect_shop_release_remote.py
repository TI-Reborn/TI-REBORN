"""Inspect shop candidate baseline with explicit transport diagnostics."""
import json,shlex,subprocess
from pathlib import Path
from tools.deploy_stage4_economy import SSH
from tools.inspect_gameplay_completion import INSPECT

def main():
    folder=Path(__file__).resolve().parents[1]/'reports/gameplay-completion/stage10-shops-r2'
    target=folder/'remote-baseline.json'
    if target.exists():raise ValueError('Preserve previous baseline')
    files=json.loads((folder/'runtime-files.json').read_text())
    result=subprocess.run(SSH+['python3 -c '+shlex.quote(INSPECT)],input=json.dumps(dict(files=files)),text=True,encoding='utf-8',capture_output=True,timeout=50)
    if result.returncode:
        # This read-only program has no credential/env/config-value inputs.
        evidence=dict(exit_code=result.returncode,read_only=True,stderr=result.stderr[-2000:])
        (folder/'inspection-transport-failure.json').write_text(json.dumps(evidence,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(evidence));return 1
    value=json.loads(result.stdout);target.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(integrity=value['integrity'],game_connections=value['game_connections'],accounts=value['tables']['accounts']['rows'],sc_seconds_to_close=value['sc_seconds_to_close'])))
    return 0

if __name__=='__main__':raise SystemExit(main())
