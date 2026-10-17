"""Read-only hosting inspection and isolated reproductions; never deploys."""
from contextlib import closing
from dataclasses import replace
from pathlib import Path
import hashlib
import json
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def isolated_probes():
    from tests.test_shared_team_arena import SharedTeamTests
    from tio.protocol.battle_attack import AttackRequest, encode_attack_request
    from tio.player_statistics import battle_report
    from types import SimpleNamespace
    results = {}
    case = SharedTeamTests()
    case.setUp()
    try:
        owners, battle = case.open_battle()
        field = battle['field']
        attacker, victim = (field.actor_ids(o)[0] for o in owners)
        # A real authoritative melee attack, with deterministic RNG and a
        # wounded victim. Bots keep the opposing side alive after this kill.
        field._actors[victim] = replace(field.actor(victim), x=5, y=6, health=1)
        field.combat.rng = SimpleNamespace(randrange=lambda n:0, randint=lambda a,b:a)
        case.send(0, encode_attack_request(AttackRequest(attacker,5,6)))
        assert (attacker, victim) in field.combat.rank_kills
        results['rating_before_departure'] = battle_report(field.combat, owners[0])
        case.hub.disconnect(case.sessions[1])
        case.now = case.hub.offline[owners[1]]
        case.hub.expire_reconnects()
        assert victim not in field._actors
        try:
            case.hub.settle(battle,owners[0],1)
        except Exception as exc:
            results['settlement_after_departure'] = dict(error=type(exc).__name__, detail=str(exc))
        else:
            results['settlement_after_departure'] = dict(error=None)
        with closing(sqlite3.connect(case.path)) as db:
            results['settled_accounts'] = [r[0] for r in db.execute('SELECT account FROM battle_rewards')]
    finally:
        case.doCleanups()

    case = SharedTeamTests()
    case.setUp()
    try:
        owners,battle=case.open_battle();field=battle['field']
        attacker,victim=(field.actor_ids(o)[0] for o in owners)
        field._actors[victim]=replace(field.actor(victim),x=5,y=6,health=1)
        field.combat.rng=SimpleNamespace(randrange=lambda n:0,randint=lambda a,b:a)
        case.send(0,encode_attack_request(AttackRequest(attacker,5,6)))
        try:case.hub.shutdown_battles()
        except Exception as exc:results['shutdown_after_pvp_kill']=dict(error=type(exc).__name__,detail=str(exc))
        else:results['shutdown_after_pvp_kill']=dict(error=None)
        with closing(sqlite3.connect(case.path)) as db:
            results['shutdown_settled_accounts']=[r[0] for r in db.execute('SELECT account FROM battle_rewards')]
    finally:case.doCleanups()

    case = SharedTeamTests()
    case.setUp()
    try:
        from tests.test_combat import item
        from tio.protocol.item_list import encode_item_list,decode_item_list
        from tio.protocol.item_action import ItemAction
        from tio.protocol.pet_info import decode_pet_info
        owners,battle=case.open_battle();field=battle['field'];combat=field.combat
        actor=field.actor_ids(owners[0])[0]
        medicine=item(200,10,2)
        combat.register(actor,encode_item_list(actor,(medicine,)),human=True)
        with closing(sqlite3.connect(case.path)) as db,db:
            db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=1',
                       (encode_item_list(1,(medicine,)),'alice'))
            saved_hp=decode_pet_info(db.execute('SELECT pet_packet FROM owned_pets WHERE account=? AND pet_id=1',
                                              ('alice',)).fetchone()[0],human_equipment=True).fields['0x8c4ab1']
        field._actors[actor]=replace(field.actor(actor),health=20)
        combat.use_medical(owners[0],ItemAction(actor,200,255))
        with closing(sqlite3.connect(case.path)) as db:
            pet,bag=db.execute('SELECT pet_packet,inventory_packet FROM owned_pets WHERE account=? AND pet_id=1',
                               ('alice',)).fetchone()
            results['unsettled_medical_persistence']=dict(live_hp=field.actor(actor).health,
                saved_hp_before=saved_hp,saved_hp_after=decode_pet_info(pet,human_equipment=True).fields['0x8c4ab1'],
                medicine_before=2,medicine_saved_after=decode_item_list(bag)[1][0].count,
                battle_rows=db.execute("SELECT count(*) FROM sqlite_master WHERE name='battle_rewards'").fetchone()[0])
    finally:case.doCleanups()

    from tests.test_sc_shop import SCShopTests, request
    from tio.protocol.item_list import decode_item_list
    from tio.wallets import WalletStore
    case = SCShopTests()
    case.setUp()
    try:
        for _ in range(19):
            replies = case.store.handle('alice', request(6,case.lot,1,2))
        results['sc_inventory_capacity'] = dict(configured_slots=18,
            saved_items=len(decode_item_list(replies[0])[1]),
            gold_after=WalletStore(case.path).ensure('alice').gold)
    finally:
        case.doCleanups()

    from server.accounts import Accounts
    from tio.protocol.login import BasicLoginRequest, encode_basic_login_request, decode_basic_login_request
    from tio.protocol.transport import InitialCipher, InitialFrameReader, encode_initial_frame
    with tempfile.TemporaryDirectory() as folder:
        accounts = Accounts(Path(folder)/'test.sqlite3')
        accounts.create('audituser','testpassword1234')
        start = time.perf_counter()
        for _ in range(3):
            try: accounts.verify(b'nonexistent', b'incorrect')
            except ValueError: pass
        results['authentication_hash_work'] = dict(attempts=3,seconds=round(time.perf_counter()-start,4))
    # Synthetic credentials only: demonstrates publicly known transport key.
    login=BasicLoginRequest(b'audituser',b'synthetic-password-only',0)
    wire=encode_initial_frame(encode_basic_login_request(login),InitialCipher('C2S'))
    reader=InitialFrameReader(InitialCipher('C2S'))
    recovered=decode_basic_login_request(reader.feed(wire)[0])
    results['public_key_recovers_synthetic_login_password']=recovered.password_bytes==login.password_bytes
    return results


def remote_inspection():
    files = [str(p.relative_to(ROOT)).replace('\\','/')
             for folder in ('tio','server','registration','config')
             for p in (ROOT/folder).rglob('*') if p.suffix in ('.py','.json')]
    code = '''import pathlib,json,sqlite3,hashlib,subprocess,sys,time
root=pathlib.Path('/opt/tio-emulator');names=json.load(sys.stdin)
def run(args):
 p=subprocess.run(args,capture_output=True,text=True);return dict(code=p.returncode,output=p.stdout.strip())
db=sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)
tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
counts={t:db.execute('SELECT count(*) FROM "'+t.replace('"','""')+'"').fetchone()[0] for t in tables}
out=dict(timestamp_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
quick_check=db.execute('PRAGMA quick_check').fetchone()[0],tables=counts,
files={n:hashlib.sha256((root/n).read_bytes()).hexdigest() if (root/n).is_file() else None for n in names},
service=run(['systemctl','show','tio-server','-p','ActiveState','-p','SubState','-p','User','-p','NRestarts','-p','ActiveEnterTimestamp','-p','ExecMainStatus']),
backup_timer=run(['systemctl','show','tio-backup.timer','-p','ActiveState','-p','LastTriggerUSec','-p','NextElapseUSecRealtime']),
backup_service=run(['systemctl','show','tio-backup.service','-p','Result','-p','ExecMainStatus']),
firewall=run(['ufw','status']),
fail2ban=run(['systemctl','is-active','fail2ban']),
listeners=run(['ss','-ltn']),
backups=[dict(name=p.name,size=p.stat().st_size,modified=p.stat().st_mtime) for p in pathlib.Path('/var/backups/tio-server').glob('*.sqlite3')],
backup_timers=run(['systemctl','list-timers','--all','--no-pager']))
print(json.dumps(out))'''
    cmd=['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes',
         '-o','ConnectTimeout=10','root@185.184.42.88','python3 -c '+shlex.quote(code)]
    data=json.loads(subprocess.run(cmd,input=json.dumps(files),capture_output=True,text=True,
                                   encoding='utf-8',check=True,timeout=90).stdout)
    data['local_file_count']=len(files)
    data['differences']={n:dict(remote=h,local=hashlib.sha256((ROOT/n).read_bytes()).hexdigest())
                        for n,h in data['files'].items() if h!=hashlib.sha256((ROOT/n).read_bytes()).hexdigest()}
    return data


def main():
    folder=ROOT/'reports/project-audit-20261001';folder.mkdir(parents=True,exist_ok=True)
    if '--remote' in sys.argv:
        result=remote_inspection();name='hosting.json'
    else:
        result=isolated_probes();name='probes.json'
    (folder/name).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if name=='hosting.json':
        print(json.dumps({k:v for k,v in result.items() if k not in ('files','tables','backups')},ensure_ascii=False,indent=2))
    else: print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
