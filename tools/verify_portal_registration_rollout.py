"""Record final read-only hosted account-preservation and service evidence."""
import argparse
import json
from pathlib import Path
import re
import subprocess

REMOTE = r'''
from contextlib import closing
from datetime import datetime, timezone
import json, sqlite3, subprocess
from pathlib import Path
settings=SETTINGS
with closing(sqlite3.connect('file:'+settings['backup']+'/reservation.sqlite3?mode=ro',uri=True)) as before, closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)) as live:
    old=before.execute('SELECT login,salt,digest,iterations FROM accounts ORDER BY login').fetchall()
    current=dict((row[0],row) for row in live.execute('SELECT login,salt,digest,iterations FROM accounts'))
    preserved=all(current.get(row[0])==row for row in old)
    game={'previous_accounts':len(old),'current_accounts':len(current),'all_original_credentials_preserved':preserved}
sql="""SELECT json_build_object('total',count(*),'legacy_active',count(*) FILTER (WHERE status='ACTIVE' AND "emailVerificationRequired"=false),'verified_required_active',count(*) FILTER (WHERE status='ACTIVE' AND "emailVerificationRequired"=true AND "emailVerifiedAt" IS NOT NULL),'pending',count(*) FILTER (WHERE status='PENDING')) FROM "User"
"""
website=json.loads(subprocess.run(['runuser','-u','postgres','--','psql','-X','-qAt','-v','ON_ERROR_STOP=1','-d','tionline_web','-c',sql],check=True,text=True,capture_output=True).stdout)
services={}
for name in ('tio-server','tio-portal','tio-game-api','nginx'):
    output=subprocess.run(['systemctl','show',name,'--property=ActiveState','--property=MainPID','--property=NRestarts'],check=True,text=True,capture_output=True).stdout
    services[name]=dict(line.split('=',1) for line in output.strip().splitlines())
identity_unchanged=services['tio-server']==settings['game_service']
release=str(Path('/opt/tio-portal/current').resolve(strict=True))
result={'created_utc':datetime.now(timezone.utc).isoformat(),'read_only':True,'game_accounts':game,'website_accounts':website,'services':services,'release':release,'game_identity_unchanged':identity_unchanged,'local_player_data_uploaded':False,'graphical_game_client_validated':False,'passed':preserved and identity_unchanged and release==settings['release'] and all(service['ActiveState']=='active' for service in services.values())}
print(json.dumps(result))
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup-report',type=Path,required=True)
    parser.add_argument('--deployment-report',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    if args.report.exists():parser.error('Preserve the existing rollout evidence')
    backup=json.loads(args.backup_report.read_text(encoding='utf-8'))
    deployment=json.loads(args.deployment_report.read_text(encoding='utf-8'))
    assert re.fullmatch(r'/root/tio-before-site-backups-[a-z0-9_]+',backup['backup'])
    assert deployment['backup']==backup['backup']
    settings={'backup':backup['backup'],'game_service':deployment['game_service'],'release':deployment['release']}
    result=subprocess.run(['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','-o','ConnectTimeout=15','root@185.184.42.88','python3 -'],input=REMOTE.replace('SETTINGS',repr(settings),1),text=True,capture_output=True,check=True,timeout=40)
    evidence=json.loads(result.stdout)
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(evidence,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(evidence))
    return 0 if evidence['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
