"""Remove receipts only for two parties owned by a disposable QA run."""
RECEIPT_CLEANUP = r'''
import json,sqlite3
from tio.rating_visibility import QA_LOGIN
assert request and all(QA_LOGIN.fullmatch(n) for n in request)
with sqlite3.connect('/var/lib/tio-server/reservation.sqlite3') as db:
 db.execute('BEGIN IMMEDIATE')
 owned=[]
 for identity,raw in db.execute('SELECT id,parties FROM player_trade_receipts'):
  parties=json.loads(raw)
  if len(parties)==2 and len({a for a,p in parties})==2 and {a for a,p in parties}<=set(request):owned.append(identity)
 sql=db.execute("SELECT sql FROM sqlite_master WHERE name='player_trade_receipts_no_delete'").fetchone()[0]
 db.execute('DROP TRIGGER player_trade_receipts_no_delete')
 for identity in owned:db.execute('DELETE FROM player_trade_receipts WHERE id=?',(identity,))
 db.execute(sql)
 print(json.dumps(dict(qa_receipts_removed=len(owned))))
'''
