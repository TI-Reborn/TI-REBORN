"""Run: python tools/balance_editor.py --open (Python standard library only)."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import sys
import webbrowser
from urllib.parse import urlsplit
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.balance_editor_core import Catalog, EditorError, ProfileStore, dumps, read_json

ASSETS = Path(__file__).with_name('balance_editor_ui')
MAX_BODY = 2 * 1024 * 1024


def make_server(store, port=8766):
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        server_version = 'TIOBalanceEditor/1'

        def log_message(self, fmt, *args):
            pass

        def reply(self, status, content, content_type='application/json; charset=utf-8', filename=None):
            raw = content if isinstance(content, bytes) else (dumps(content) if isinstance(content, (dict, list)) else content).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
            if filename:
                self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(raw)

        def check(self, api=False):
            port = self.server.server_address[1]
            allowed = {f'127.0.0.1:{port}', f'localhost:{port}'}
            if self.headers.get('Host') not in allowed:
                raise EditorError('Недопустимый адрес редактора', 403)
            origin = self.headers.get('Origin')
            if origin is not None and origin not in {f'http://{h}' for h in allowed}:
                raise EditorError('Запрос из другого сайта запрещён', 403)
            if api and not secrets.compare_digest(self.headers.get('X-Editor-Token', ''), token):
                raise EditorError('Обновите страницу редактора', 403)

        def do_GET(self):
            try:
                path = urlsplit(self.path).path
                self.check(api=path.startswith('/api/'))
                if path == '/':
                    html = (ASSETS/'index.html').read_text(encoding='utf-8').replace('__EDITOR_TOKEN__', token)
                    return self.reply(200, html, 'text/html; charset=utf-8')
                if path in ('/app.js', '/style.css'):
                    return self.reply(200, (ASSETS/path[1:]).read_bytes(),
                        'text/javascript; charset=utf-8' if path.endswith('.js') else 'text/css; charset=utf-8')
                if path == '/api/state':
                    return self.reply(200, store.state())
                match = re.fullmatch(r'/api/profiles/([0-9a-f]{32})(/profile|/candidate)?', path)
                if match:
                    identity, action = match.groups()
                    if action == '/profile':
                        return self.reply(200, store.load(identity), filename='balance-profile.json')
                    if action == '/candidate':
                        return self.reply(200, store.export(identity), 'application/zip', 'balance-candidate.zip')
                    return self.reply(200, store.state(store.load(identity)))
                raise EditorError('Страница не найдена', 404)
            except EditorError as exc:
                self.reply(exc.status, {'error': str(exc)})
            except (ValueError, KeyError, TypeError, OSError) as exc:
                self.reply(400, {'error': 'Не удалось прочитать каталог или профиль: ' + str(exc)})

        def do_POST(self):
            try:
                self.check(api=True)
                if self.headers.get('Content-Type', '').split(';')[0].strip() != 'application/json':
                    raise EditorError('Ожидается JSON', 415)
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= MAX_BODY:
                    raise EditorError('Размер запроса превышает лимит', 413)
                data = read_json(self.rfile.read(size))
                if not isinstance(data, dict):
                    raise EditorError('Ожидается объект JSON')
                path = urlsplit(self.path).path
                if path == '/api/profiles':
                    return self.reply(201, store.state(store.create(data.get('name'))))
                if path == '/api/import':
                    imported = data.get('profile')
                    return self.reply(201, store.state(store.create(data.get('name'), imported=imported)))
                match = re.fullmatch(r'/api/profiles/([0-9a-f]{32})', path)
                if match:
                    profile = store.save(match[1], data.get('revision'), data.get('name'), data.get('changes'))
                    return self.reply(200, store.state(profile))
                if path == '/api/preview':
                    profile = store.load(data['profile_id']) if data.get('profile_id') else None
                    documents = profile['documents'] if profile else store.snapshot()
                    result = Catalog(documents).preview(data.get('changes', {}), data.get('item_id'),
                                                       data.get('defense', 0), data.get('budget', 20))
                    return self.reply(200, result)
                raise EditorError('Операция не найдена', 404)
            except EditorError as exc:
                self.reply(exc.status, {'error': str(exc)})
            except (ValueError, KeyError, TypeError, AttributeError, OSError) as exc:
                self.reply(400, {'error': 'Некорректные данные: ' + str(exc)})

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='Локальный редактор профилей баланса TIO')
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--open', action='store_true', help='Открыть браузер')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('Порт должен быть от 1 до 65535')
    store = ProfileStore()
    Catalog(store.snapshot())
    try:
        server = make_server(store, args.port)
    except OSError as exc:
        if args.open:
            try:
                url = f'http://127.0.0.1:{args.port}/'
                with urlopen(url, timeout=2) as response:
                    running = response.headers.get('Server', '').startswith('TIOBalanceEditor/1')
                if running:
                    webbrowser.open(url)
                    return
            except OSError:
                pass
        parser.exit(1, f'Не удалось открыть порт {args.port}: {exc}\n')
    url = f'http://127.0.0.1:{server.server_address[1]}/'
    receipt = store.directory.parent/'server.json'
    receipt.write_text(dumps({'pid': os.getpid(), 'url': url}), encoding='utf-8')
    print(f'TIO Balance Editor: {url}\nПрофили: {store.directory}\nCtrl+C — остановить.', flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
