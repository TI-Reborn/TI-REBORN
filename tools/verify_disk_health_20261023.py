"""Hosted read-only DB checks and an isolated disposable write test as tio."""
import json
import http.client
import os
from pathlib import Path
import socket
import sqlite3
import ssl
import subprocess
import time


def main():
    started = time.time()
    with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro', uri=True) as db:
        db.execute('PRAGMA query_only=ON')
        assert db.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
        pages = db.execute('PRAGMA page_count').fetchone()[0]
        limit = db.execute('PRAGMA max_page_count').fetchone()[0]
    probe = r'''
import json, sqlite3, tempfile
from pathlib import Path
with tempfile.TemporaryDirectory(prefix='.disk-write-probe-',dir='/var/lib/tio-server') as directory:
    assert Path(directory).resolve().parent == Path('/var/lib/tio-server')
    with sqlite3.connect(Path(directory)/'probe.sqlite3') as db:
        db.execute('PRAGMA synchronous=FULL')
        db.execute('CREATE TABLE write_probe(value BLOB)')
        db.execute('INSERT INTO write_probe VALUES (zeroblob(1048576))')
        db.commit()
        assert db.execute('SELECT length(value) FROM write_probe').fetchone() == (1048576,)
        assert db.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
print(json.dumps({'user':'tio','committed_bytes':1048576,'integrity':'ok','scratch_removed':not Path(directory).exists()}))
'''
    tested = subprocess.run(['runuser', '-u', 'tio', '--', 'python3', '-'], input=probe,
                            check=True, capture_output=True, text=True)
    services = {}
    for name in ('tio-server', 'tio-portal', 'tio-game-api', 'postgresql', 'nginx'):
        services[name] = subprocess.check_output(['systemctl', 'is-active', name], text=True).strip()
        assert services[name] == 'active'
    identity = subprocess.check_output(['systemctl', 'show', 'tio-server', '-p', 'MainPID', '-p', 'NRestarts'], text=True)
    assert identity == 'MainPID=440738\nNRestarts=19\n'
    ports = subprocess.check_output(['ss', '-ltnH'], text=True)
    for port in (28512, 28513, 29512, 29513):
        assert any(line.split()[3].endswith(':'+str(port)) for line in ports.splitlines())
    # Verify the origin directly; the public CDN may reject VPS-origin requests.
    connection = http.client.HTTPConnection('ti-reborn.com', timeout=20)
    connection.sock = ssl.create_default_context().wrap_socket(
        socket.create_connection(('127.0.0.1', 443), timeout=20), server_hostname='ti-reborn.com')
    try:
        connection.request('GET', '/ru')
        response = connection.getresponse()
        assert response.status == 200, response.status
        response.read()
    finally:
        connection.close()
    available = os.statvfs('/')
    assert available.f_bavail * available.f_frsize > 6 * 1024**3
    journal = subprocess.check_output(['journalctl', '-u', 'tio-server', '--since',
                    '@'+str(int(started)), '--no-pager'], text=True)
    assert 'database or disk is full' not in journal and 'Traceback' not in journal
    print(json.dumps(dict(live_sqlite_integrity='ok', page_count=pages, max_page_count=limit,
                          database_write_probe=json.loads(tested.stdout), services=services,
                          game_listeners=[28512,28513,29512,29513], website_origin_http_status=200,
                          available_bytes=available.f_bavail*available.f_frsize,
                          game_identity_unchanged=True, new_storage_errors=False), indent=2))


if __name__ == '__main__':
    main()
