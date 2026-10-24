"""Second excluded real account for shared hosted battle rendering QA."""
from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.verify_area_fire_hosted_20261018 import Network,STATE
from tools.verify_game_operations_hosted import remote
from tools.personal_gui_all_qa_20261020 import qa,OUT

data=json.loads(qa.PRIVATE.read_text());net=Network(data)
try:
    net.connect(1)
    print(json.dumps({'second_real_account_authenticated':True,'ranking_excluded':True}),flush=True)
    for line in sys.stdin:
        action=line.strip()
        if action=='stop':break
        if action=='join':net.command(1,b'\xba\3\0\1')
        elif action=='loaded':net.command(1,b'\x36')
        elif action=='leave':net.command(1,b'\x2a\1')
        else:net.command(1)
        frame=remote(STATE,dict(names=data['names'],plan=False))
        (OUT/'hosted-battle-state.json').write_text(json.dumps(frame,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({'action':action,'shared_battle':frame is not None,
                          'two_real_accounts':bool(frame and len(frame['actors'])==2),'bots':frame.get('bots') if frame else None}),flush=True)
finally:
    try:net.command(1,b'\x2a\1')
    except Exception:pass
    net.close()
