"""Run on the host: owned fixtures, HTTP recovery and authoritative TLS auth."""
import hashlib, http.cookies, json, secrets, socket, sqlite3, ssl, struct
import subprocess, sys, urllib.request, urllib.error, uuid
from collections import deque
from pathlib import Path
sys.path.insert(0, '/opt/tio-emulator')
from tio.protocol.transport import (InitialCipher, InitialFrameReader, InitialReply, encode_initial_reply,
    encode_initial_frame, decode_initial_challenge, decode_initial_completion, expected_reply_fields)
from tio.protocol.login import BasicLoginRequest, encode_basic_login_request, transform_auth_value
ORIGIN = 'https://ti-reborn.com'
BASE = 'http://127.0.0.1:3000'

def sql(statement):
    return subprocess.check_output(['runuser', '-u', 'postgres', '--', 'psql', '-XqAt', '-v',
        'ON_ERROR_STOP=1', '-d', 'tionline_web', '-c', statement], text=True).strip()

class Browser:
    def __init__(self): self.cookies = {}; self.ip = '192.0.2.'+str(secrets.randbelow(200)+10)
    def request(self, path, body=None):
        headers = {'Cookie': '; '.join(k+'='+v for k,v in self.cookies.items()), 'X-Real-IP': self.ip}
        data = None
        if body is not None:
            token = self.request('/api/auth/session')[1]['csrfToken']
            headers.update({'Origin': ORIGIN, 'X-CSRF-Token': token, 'Content-Type': 'application/json'})
            headers['Cookie'] = '; '.join(k+'='+v for k,v in self.cookies.items())
            data = json.dumps(body).encode()
        req = urllib.request.Request(BASE+path, data=data, headers=headers)
        try: response = urllib.request.urlopen(req, timeout=25)
        except urllib.error.HTTPError as error: response = error
        with response:
            for value in response.headers.get_all('Set-Cookie', []):
                cookie = http.cookies.SimpleCookie(); cookie.load(value)
                for key, morsel in cookie.items(): self.cookies[key] = morsel.value
            raw = response.read()
            return response.status, json.loads(raw) if response.headers.get('Content-Type', '').startswith('application/json') else raw.decode()

def game_login(name, password):
    manifest = Path('/var/www/tio-client/updates/manifest.json').read_bytes()
    version = json.loads(Path('/var/www/tio-client/downloads/launcher-manifest.json').read_bytes())['version']
    context = ssl.create_default_context(); context.keylog_filename = None
    with socket.create_connection(('127.0.0.1', 29512), timeout=15) as raw, context.wrap_socket(raw, server_hostname='ti-reborn.com') as connection:
        connection.sendall(b'TIOT\x02\x00'+struct.pack('!H', 28513)+hashlib.sha256(manifest).digest()+struct.pack('!HHH', *map(int, version.split('.'))))
        reader = InitialFrameReader(InitialCipher('S2C')); writer = InitialCipher('C2S'); pending = deque()
        def receive():
            while not pending:
                block = connection.recv(65536)
                if not block: raise RuntimeError('TLS authentication ended early')
                pending.extend(reader.feed(block))
            return pending.popleft()
        def send(packet): connection.sendall(encode_initial_frame(packet, writer))
        fields = expected_reply_fields(decode_initial_challenge(receive()))
        send(encode_initial_reply(InitialReply(*fields, 0, bytes(3))))
        token = decode_initial_completion(receive()).unknown_u32_01
        send(encode_basic_login_request(BasicLoginRequest(name.encode(), password.encode(), transform_auth_value(token))))
        assert receive() == b'\x04\x00', 'Hosted TLS login rejected'

def main():
    checks, owned = [], []
    dbpath = '/var/lib/tio-server/reservation.sqlite3'
    with sqlite3.connect('file:'+dbpath+'?mode=ro', uri=True) as db:
        original = set(db.execute('SELECT login,salt,digest,iterations FROM accounts'))
    service = subprocess.check_output(['systemctl', 'show', 'tio-server', '-p', 'MainPID', '-p', 'NRestarts'], text=True)
    try:
        for length in [32, 64]:
            name = 'qa_mail_'+secrets.token_hex(6); uid = str(uuid.uuid4()); owned.append((uid, name))
            email = 'delivered+'+name+'@resend.dev'
            sql(f'''INSERT INTO "User" (id,username,email,"passwordHash","gameUsername","provisioningId",role,status,"emailVerificationRequired","createdAt","updatedAt") VALUES ('{uid}','{name}','{email}','!owned-test-only','{name}','{uuid.uuid4()}','PLAYER','PENDING',true,now(),now())''')
            browser = Browser()
            assert browser.request('/api/auth/password-reset/request', {'email': email, 'locale': 'ru'})[0] == 200
            assert sql(f'''SELECT count(*) FROM "PasswordReset" WHERE "userId"='{uid}' AND "expiresAt">now() AND "consumedAt" IS NULL''') == '1'
            # Only the newly owned profile gets a known test token. This is
            # separate from real inbox delivery and CAPTCHA signup validation.
            token = secrets.token_urlsafe(32); digest = hashlib.sha256(token.encode()).hexdigest()
            sql(f'''UPDATE "PasswordReset" SET "tokenHash"='{digest}' WHERE "userId"='{uid}' ''')
            assert browser.request('/ru/password-reset')[0] == 200
            password = ('A7!'+secrets.token_urlsafe(48))[:length]
            body = {'token': token, 'newPassword': password, 'confirmPassword': password}
            assert browser.request('/api/auth/password-reset/complete', {**body, 'newPassword': 'A7!'+('x'*62), 'confirmPassword': 'A7!'+('x'*62)})[0] == 400
            assert browser.request('/api/auth/password-reset/complete', body)[0] == 200
            assert browser.request('/api/auth/password-reset/complete', body)[0] == 400
            assert browser.request('/api/auth/login', {'username': name, 'password': password})[0] == 200
            game_login(name, password)
            check = {'password_characters': length, 'pending_recovery': True, 'website_login': True,
                'hosted_game_tls_login': True, 'single_use': True, 'overlong_rejected': True}
            checks.append(check)
            sql(f'''UPDATE "PasswordReset" SET "sentAt"=now()-interval '61 seconds' WHERE "userId"='{uid}' ''')
            anonymous = Browser()
            assert anonymous.request('/api/auth/password-reset/request', {'email': email})[0] == 200
            token = secrets.token_urlsafe(32); digest = hashlib.sha256(token.encode()).hexdigest()
            sql(f'''UPDATE "PasswordReset" SET "tokenHash"='{digest}' WHERE "userId"='{uid}' ''')
            changed = ('B9!'+secrets.token_urlsafe(48))[:length]
            assert anonymous.request('/api/auth/password-reset/complete', {'token': token, 'newPassword': changed, 'confirmPassword': changed})[0] == 200
            assert browser.request('/api/auth/session')[1]['user'] is None
            assert anonymous.request('/api/auth/login', {'username': name, 'password': password})[0] == 401
            assert anonymous.request('/api/auth/login', {'username': name, 'password': changed})[0] == 200
            game_login(name, changed)
            check.update(active_recovery=True, old_password_rejected=True, old_sessions_revoked=True)
    finally:
        for uid, name in owned:
            assert name.startswith('qa_mail_') and len(name) == 20
            sql(f'''DELETE FROM "User" WHERE id='{uid}' AND username='{name}' ''')
            with sqlite3.connect(dbpath) as db:
                assert db.execute('SELECT count(*) FROM characters WHERE account=?', (name,)).fetchone()[0] == 0
                db.execute('DELETE FROM game_web_receipts WHERE login=?', (name,))
                db.execute('DELETE FROM accounts WHERE login=?', (name,)); db.commit()
    with sqlite3.connect('file:'+dbpath+'?mode=ro', uri=True) as db:
        after = set(db.execute('SELECT login,salt,digest,iterations FROM accounts'))
        integrity = db.execute('PRAGMA integrity_check').fetchone()[0]
    assert original <= after and integrity == 'ok'
    print(json.dumps({'passed': True, 'checks': checks, 'owned_fixtures_removed': len(owned),
        'existing_game_credentials_preserved': True, 'sqlite_integrity': integrity,
        'game_service_unchanged': service == subprocess.check_output(['systemctl', 'show', 'tio-server', '-p', 'MainPID', '-p', 'NRestarts'], text=True),
        'mail_transport': 'production provider attempted; test proof injected only into owned simulated-mailbox profiles',
        'real_inbox_delivery_verified': False, 'graphical_login_verified': False}))

if __name__ == '__main__': main()
