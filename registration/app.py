import hmac
import secrets
import sqlite3
import threading
import time
from urllib.parse import urlsplit

from flask import Flask, abort, redirect, render_template, request, session
from server.accounts import Accounts


class Limiter:
    """Bound CPU/DB work: per-IP and global rolling request windows."""
    def __init__(self):
        self.lock = threading.Lock()
        self.attempts = []

    def allow(self, ip):
        now = time.monotonic()
        with self.lock:
            self.attempts = [(t, key) for t, key in self.attempts if now-t < 3600]
            if len(self.attempts) >= 100 or sum(key == ip for _, key in self.attempts) >= 5:
                return False
            self.attempts.append((now, ip))
            return True


def create_app(database, secret, origin):
    parsed = urlsplit(origin)
    if parsed.scheme != 'https' or not parsed.netloc or parsed.path or parsed.query or parsed.fragment:
        raise ValueError('Origin must be an HTTPS origin without a path')
    if len(secret) < 32:
        raise ValueError('Session secret must contain at least 32 characters')
    accounts = Accounts(database)
    accounts.check()  # Fail closed if pointed at the wrong/uninitialized database.
    app = Flask(__name__)
    app.config.update(SECRET_KEY=secret, SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict',
        MAX_CONTENT_LENGTH=4096, MAX_FORM_MEMORY_SIZE=4096,
        TRUSTED_HOSTS=[parsed.hostname], PERMANENT_SESSION_LIFETIME=1800)
    limiter = Limiter()

    @app.before_request
    def secure_request():
        if not request.is_secure:
            abort(400)

    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Content-Security-Policy'] = "default-src 'none'; style-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
        response.headers['X-Content-Type-Options'] = 'nosniff'
        # HTML form POST under no-referrer sends Origin: null in browsers,
        # contradicting our strict same-origin check. Keep that check and CSRF.
        response.headers['Referrer-Policy'] = 'same-origin'
        return response

    @app.get('/')
    def index():
        return redirect('/register/')

    @app.route('/register/', methods=['GET', 'POST'])
    def register():
        if request.method in ('GET', 'HEAD'):
            session['csrf'] = secrets.token_urlsafe(32)
            session.permanent = True
            return render_template('register.html', token=session['csrf'])
        if request.headers.get('Origin') != origin:
            abort(403)
        token = request.form.get('csrf', '')
        expected = session.get('csrf', '')
        if not expected or not hmac.compare_digest(token.encode(), expected.encode()):
            abort(403)
        session.pop('csrf', None)
        if not limiter.allow(request.remote_addr):
            return render_template('result.html', message='Слишком много попыток. Попробуйте через час.'), 429
        login = request.form.get('login', '')
        password = request.form.get('password', '')
        if password != request.form.get('confirm', ''):
            return render_template('result.html', message='Пароли не совпадают. Вернитесь к регистрации.'), 400
        try:
            accounts.create(login, password)
        except (ValueError, sqlite3.IntegrityError):
            return render_template('result.html', message='Проверьте формат данных. Логин может быть занят.'), 400
        except sqlite3.OperationalError:
            app.logger.warning('Registration database unavailable')
            return render_template('result.html', message='Сервис временно недоступен. Попробуйте позже.'), 503
        return render_template('result.html', message='Аккаунт создан. Вернитесь в игру, выберите «Онлайн игра» и введите свой логин и пароль. После выбора сервера создайте персонажа: укажите имя и пол.'), 201

    return app
