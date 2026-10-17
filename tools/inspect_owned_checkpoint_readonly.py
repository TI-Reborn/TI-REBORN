"""Inspect only checkpoint timing and table shape, without exposing battle payloads."""
import json
from tools.deploy_stage4_economy import remote

CODE = r'''
import json,sqlite3,time
from contextlib import closing
with closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)) as db:
 columns=[r[1] for r in db.execute('PRAGMA table_info(battle_checkpoints)')]
 permitted=[c for c in columns if c in ('id','kind','created','updated','expires','updated_at','expires_at','state','version','status','error_type','revision')]
 rows=[dict(zip(permitted,r)) for r in db.execute('SELECT '+','.join('"'+c+'"' for c in permitted)+' FROM battle_checkpoints')] if permitted else []
 print(json.dumps(dict(now=time.time(),columns=columns,checkpoints=rows,settlement_jobs=db.execute('SELECT COUNT(*) FROM battle_settlement_jobs').fetchone()[0])))
'''
if __name__ == '__main__':
    print(json.dumps(remote(CODE, {})))
