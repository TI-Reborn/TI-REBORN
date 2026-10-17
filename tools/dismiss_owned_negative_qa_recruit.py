"""Prepare owned D's negative GUI case using a genuine hosted dismissal.

No local save upload or direct player-data rewrite. A fresh remote backup
precedes authenticated TLS opcode64; only the verified empty hired recruit2
of the archived, disposable QA account D may be dismissed.
"""
from pathlib import Path
import json

from tools.verify_legacy_lobbies_hosted import LobbyTlsQA, FreshSurroundingsQA, OWNERSHIP
from tools.verify_game_tls_hosted import TlsNetworkQA, tls_context, require
from tio.protocol.hire import encode_dismiss_request

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'reports/gameplay-completion/legacy-status-20261011/gui'
FIXTURE=ROOT/'reports/arena-surroundings/private/qs3110ad96.json'

PREPARE=OWNERSHIP+r'''
from contextlib import closing
from pathlib import Path
import hashlib,tempfile,shutil
from tio.protocol.pet_info import decode_pet_info
from tio.protocol.item_list import decode_item_list
assert names==['qs3110ad96a','qs3110ad96b','qs3110ad96c','qs3110ad96d']
target=names[3];path=Path('/var/lib/tio-server/reservation.sqlite3')
with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
 db.execute('BEGIN')
 assert not db.execute('SELECT 1 FROM battle_checkpoint_members WHERE account=?',(target,)).fetchone()
 rows=db.execute('SELECT pet_id,human,pet_packet,inventory_packet FROM owned_pets WHERE account=? ORDER BY pet_id',(target,)).fetchall()
 assert len(rows)==2 and [r[0] for r in rows]==[1,2]
 levels=[decode_pet_info(r[2],human_equipment=bool(r[1])).fields['0x8c4aef'] for r in rows]
 assert levels==[4,1]
 assert db.execute('SELECT candidate_id FROM hired_candidates WHERE account=? AND pet_id=2',(target,)).fetchone()==(0x40000000,)
 assert decode_item_list(rows[1][3])[1]==()
 assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 backup=Path(tempfile.mkdtemp(prefix='tio-before-owned-qa-dismiss-',dir='/root'))
 with closing(sqlite3.connect(backup/'reservation.sqlite3')) as destination:db.backup(destination)
 shutil.copyfile('/etc/tio-server/server.toml',backup/'server.toml')
 shutil.copyfile('/opt/tio-emulator/tio/hiring.py',backup/'hiring.py')
 print(json.dumps(dict(backup=str(backup),account=target,levels=levels,pet_id=2,direct_database_writes=False)))
'''

AFTER=OWNERSHIP+r'''
from tio.protocol.pet_info import decode_pet_info
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 rows=db.execute('SELECT pet_id,human,pet_packet FROM owned_pets WHERE account=? ORDER BY pet_id',(names[3],)).fetchall()
 assert len(rows)==1 and rows[0][0]==1
 levels=[decode_pet_info(r[2],human_equipment=bool(r[1])).fields['0x8c4aef'] for r in rows]
 assert levels==[4]
 print(json.dumps(dict(account=names[3],pet_ids=[1],levels=levels,negative_case_valid=True)))
'''

class PreparationQA(LobbyTlsQA):
    # This preparation never queues a match. The parent counts up to two
    # existing accounts, while the Lobby subclass would require an empty hub.
    begin=TlsNetworkQA.begin

def main():
    # Actual hosted64 schedules dismissal after48hours. The first diagnostic
    # attempt was stopped; retain this source for audit and refuse repetition.
    # It is not a valid immediate-removal preparation workflow.
    raise RuntimeError('Disabled: hosted64 schedules delayed dismissal; use the reviewed level fixture')
    report=FOLDER/'d-owned-recruit-dismissal.json'
    if report.exists():raise ValueError('Preserve previous dismissal evidence')
    session=json.loads((FOLDER/'d-navigation-session.json').read_text())
    require(session['client_terminated'],'Close the own graphical D first')
    fixture=FreshSurroundingsQA.load_private(FIXTURE)
    before=fixture.remote(PREPARE,fixture.ownership_payload())
    qa=PreparationQA(fixture,'185.184.42.88','ti-reborn.com',29512,29513,tls_context())
    try:
        qa.enter(3)
        replies=qa.command(3,encode_dismiss_request(2))
        qa.expect(3,replies,b'\x65\x02\0\0\0')
        require(b'\x65\x02\0\0\0' in replies,'Dismissal was not acknowledged')
    finally:
        qa.close()
    after=fixture.remote(AFTER,fixture.ownership_payload())
    result=dict(passed=True,before=before,after=after,actual_tls_protocol=True,
                native_command='6402000000',native_acknowledgement='6502000000',
                credentials_logged=False,local_player_data_uploaded=False)
    with report.open('x') as output:json.dump(result,output,indent=2)
    print(json.dumps(result))

if __name__=='__main__':main()
