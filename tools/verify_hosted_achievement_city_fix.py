"""Two disposable excluded TLS accounts test the deployed non-city delivery guard."""
from pathlib import Path
from types import SimpleNamespace
import json
import secrets
import time

from tools.prepare_achievement_city_fix import FOLDER
from tools.verify_english_localization_hosted import remote, CREATE, CLEANUP
from tools.verify_game_tls_hosted import TlsNetworkQA, tls_context

BACKUP = r'''
from contextlib import closing
from pathlib import Path
import json,sqlite3,tempfile,os
os.umask(0o077)
folder=Path(tempfile.mkdtemp(prefix='tio-before-achievement-city-qa-',dir='/root'))
with closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)) as source,closing(sqlite3.connect(folder/'reservation.sqlite3')) as target:
 source.backup(target)
 assert target.execute('PRAGMA integrity_check').fetchone()==('ok',)
print(json.dumps(dict(backup=str(folder),integrity='ok')))
'''
SEED = r'''
from tio.rating_visibility import QA_LOGIN
from tio.achievements import AchievementStore,update
from tio.locations import LocationStore,center
import sqlite3,json
names=request;assert len(names)==2 and all(QA_LOGIN.fullmatch(n) for n in names)
path='/var/lib/tio-server/reservation.sqlite3'
AchievementStore(path);LocationStore(path)
with sqlite3.connect(path) as db:
 assert all(db.execute('SELECT 1 FROM accounts WHERE login=?',(n,)).fetchone() for n in names)
 db.execute('INSERT OR REPLACE INTO character_locations VALUES (?,?,?,?)',(names[0],17,*center(17)))
 update(db,names[0],add={'melee_kills':10})
 assert db.execute('SELECT notified FROM achievement_awards WHERE account=? AND id=22',(names[0],)).fetchone()==(0,)
print(json.dumps(dict(pending_achievement=22,qa_town=17)))
'''
SNAPSHOT = r'''
from tio.rating_visibility import QA_LOGIN
import sqlite3,json
names=request;assert len(names)==2 and all(QA_LOGIN.fullmatch(n) for n in names)
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 print(json.dumps([dict(town=(db.execute('SELECT town_id FROM character_locations WHERE account=?',(n,)).fetchone() or (3,))[0],
 credits=db.execute('SELECT credits FROM wallets WHERE account=?',(n,)).fetchone()[0],
 award=db.execute('SELECT notified FROM achievement_awards WHERE account=? AND id=22',(n,)).fetchone(),
 prizes=db.execute('SELECT delivered FROM achievement_prizes WHERE account=? AND id=22',(n,)).fetchall()) for n in names]))
'''
CITY_FIXTURE = r'''
from tio.rating_visibility import QA_LOGIN
from tio.locations import center
import sqlite3,json
names=request;assert len(names)==2 and all(QA_LOGIN.fullmatch(n) for n in names)
with sqlite3.connect('/var/lib/tio-server/reservation.sqlite3') as db:
 assert not db.execute('SELECT 1 FROM battle_checkpoint_members WHERE account=?',(names[0],)).fetchone()
 assert not db.execute('SELECT 1 FROM map_journeys WHERE account=?',(names[0],)).fetchone()
 db.execute('UPDATE character_locations SET town_id=?,x=?,y=? WHERE account=?',(3,*center(3),names[0]))
print(json.dumps(dict(disconnected_qa_relocated_to_city=True)))
'''


def main():
    prefix = 'qd' + secrets.token_hex(4)
    names = [prefix + suffix for suffix in 'ab']
    fixture = SimpleNamespace(names=names, passwords=[secrets.token_urlsafe(24) for _ in names])
    report = dict(passed=False, graphical_clients=False, kind='two public TLS protocol clients', accounts=names)
    created = False
    network = TlsNetworkQA(fixture, '185.184.42.88', 'ti-reborn.com', 29512, 29513, tls_context())
    try:
        report['pre_qa_backup'] = remote(BACKUP, {})
        report['provisioning'] = remote(CREATE, list(zip(names, fixture.passwords))); created = True
        report['fixture'] = remote(SEED, names)
        peers = [network.enter(i) for i in range(2)]
        initial = remote(SNAPSHOT, names)
        assert initial[0]['town'] == 17 and initial[0]['award'] == [0] and initial[0]['prizes'] == [[0]]
        for _ in range(4):
            time.sleep(2.1)
            for peer in peers: network.ping(peer)
        assert remote(SNAPSHOT, names) == initial
        peers[0].sock.close(); time.sleep(1.2)
        peers[0] = network.enter(0)
        time.sleep(2.1)
        for peer in peers: network.ping(peer)
        assert remote(SNAPSHOT, names) == initial
        report['range_reconnect_pending_preserved'] = True
        peers[0].sock.close(); time.sleep(1.2)
        report['city_test_fixture'] = remote(CITY_FIXTURE, names)
        peers[0] = network.enter(0)
        deadline = time.monotonic() + 8
        while True:
            for peer in peers: network.ping(peer)
            final = remote(SNAPSHOT, names)
            if final[0]['prizes'] == [[1]]: break
            assert time.monotonic() < deadline
            time.sleep(.5)
        assert final[0]['award'] == [1] and final[0]['credits'] == initial[0]['credits'] + 500
        assert final[1] == initial[1]
        peers[0].sock.close(); time.sleep(1.2)
        peers[0] = network.enter(0)
        time.sleep(2.1)
        for peer in peers: network.ping(peer)
        assert remote(SNAPSHOT, names) == final
        report.update(passed=True, city_reward_credits=500, city_reward_delivered_once=True,
                      second_account_isolated=True, certificate_verified=True)
    finally:
        network.close()
        if created:
            time.sleep(1.5)
            report['cleanup'] = remote(CLEANUP, names)
        (FOLDER / 'hosted-tls-verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
