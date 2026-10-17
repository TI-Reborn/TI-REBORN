"""Black-box portal checks over trusted HTTPS; optional owned QA fixtures only.

No passwords, CSRF tokens, cookies or full response bodies enter the report.
This is automated HTTP/protocol validation, never graphical-client validation.
"""
import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import html.parser
import http.cookiejar
import json
import os
from pathlib import Path
import re
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
VISIBLE_KEY = re.compile(r'\b(?:auth|common|hero|home|nav|faq|news|download|account|status|admin|community|features|footer|meta)\.[a-z_][a-z0-9_.-]+')
CYRILLIC = re.compile(r'[А-Яа-яЁё]')


class CheckFailure(Exception):
    def __init__(self, reason='assertion_failed', *, expected=None, actual=None):
        super().__init__(reason)
        self.reason, self.expected, self.actual = reason, expected, actual


@dataclass
class Response:
    status: int
    url: str
    headers: object
    body: bytes

    def json(self):
        return json.loads(self.body.decode('utf-8'))


class Document(html.parser.HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.lang, self.title = '', ''
        self.meta, self.links, self.text = {}, [], []
        self.classes = set()
        self.hidden = 0
        self.in_title = False
        self.feed(source)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        self.classes.update(attrs.get('class', '').split())
        if tag in ('script', 'style'):
            self.hidden += 1
        if tag == 'html':
            self.lang = attrs.get('lang', '')
        if tag == 'title':
            self.in_title = True
        if tag == 'meta':
            self.meta[attrs.get('name') or attrs.get('property', '')] = attrs.get('content', '')
        if tag == 'link':
            self.links.append(attrs)

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.hidden = max(0, self.hidden-1)
        if tag == 'title':
            self.in_title = False

    def handle_data(self, value):
        if self.hidden:
            return
        if self.in_title:
            self.title += value
        self.text.append(value)

    @property
    def visible(self):
        return ' '.join(self.text)


class Client:
    def __init__(self, base_url):
        self.base_url = base_url.rstrip('/')
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def request(self, path, *, method='GET', body=None, token=None, origin=None,
                language=None, cookie=None):
        headers = {'Accept': 'application/json' if path.startswith('/api/') else 'text/html',
                   'User-Agent': 'Tionline-Portal-QA/1.0'}
        if language:
            headers['Accept-Language'] = language
        if cookie:
            headers['Cookie'] = cookie
        if origin is not None:
            headers['Origin'] = origin
        if token is not None:
            headers['X-CSRF-Token'] = token
        data = None
        if body is not None:
            headers['Content-Type'] = 'application/json'
            data = json.dumps(body, ensure_ascii=False).encode('utf-8')
        request = urllib.request.Request(self.base_url+path, data=data, headers=headers, method=method)
        try:
            response = self.opener.open(request, timeout=30)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            body_bytes = response.read(8*1024*1024+1)
            if len(body_bytes) > 8*1024*1024:
                raise CheckFailure('response_too_large')
            return Response(response.status, response.geturl(), response.headers, body_bytes)

    def session(self):
        response = self.request('/api/auth/session')
        if response.status != 200:
            raise CheckFailure('session_unavailable')
        payload = response.json()
        if not isinstance(payload.get('csrfToken'), str):
            raise CheckFailure('csrf_missing')
        return payload

    def mutate(self, path, data):
        return self.request(path, method='POST', body=data,
                            token=self.session()['csrfToken'], origin=self.base_url)


class Verifier:
    def __init__(self, base_url, report_path):
        self.base_url, self.report_path = base_url, report_path
        self.client = Client(base_url)
        self.report = dict(startedAt=datetime.now(timezone.utc).isoformat(),
            baseUrl=base_url, kind='automated trusted HTTPS and optional legacy game protocol',
            graphicalClientValidation=False, checks=[], createdFixtures=0, passed=False)
        self.fixtures = []

    def check(self, name, operation):
        try:
            detail = operation() or {}
            self.report['checks'].append(dict(name=name, passed=True, **detail))
        except Exception as error:
            # Exception messages can contain URLs, response content, or secrets.
            failure = dict(name=name, passed=False, failureType=type(error).__name__)
            if isinstance(error, CheckFailure):
                failure['reason'] = error.reason
                if error.expected is not None:
                    failure['expected'] = error.expected
                if error.actual is not None:
                    failure['actual'] = error.actual
            self.report['checks'].append(failure)
        self.save_report()

    def save_report(self):
        self.report['passed'] = all(check['passed'] for check in self.report['checks'])
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        self.report_path.write_text(json.dumps(self.report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

    @staticmethod
    def require(condition, reason='assertion_failed', *, expected=None, actual=None):
        if not condition:
            raise CheckFailure(reason, expected=expected, actual=actual)

    def route(self, locale, page):
        response = self.client.request('/'+locale+('/'+page if page else ''))
        document = Document(response.body.decode('utf-8'))
        self.require(response.status == 200, 'public_route_status', expected=200, actual=response.status)
        self.require(document.lang == locale, 'document_language', expected=locale,
                     actual=document.lang if document.lang in ('en', 'ru') else 'other')
        self.require(bool(document.title.strip()))
        self.require(not VISIBLE_KEY.search(document.visible))
        if locale == 'ru':
            self.require(bool(CYRILLIC.search(document.visible)))
        if page not in ('maintenance',):
            canonical = [link for link in document.links if link.get('rel') == 'canonical']
            alternatives = {link.get('hreflang') for link in document.links if link.get('rel') == 'alternate'}
            self.require(bool(canonical), 'canonical_missing', expected=True, actual=bool(canonical))
            self.require({'en', 'ru'} <= alternatives, 'hreflang_missing', expected=True,
                         actual={'en', 'ru'} <= alternatives)
            self.require(bool(document.meta.get('description')))
            self.require(bool(document.meta.get('og:title')))
        return {'path':'/'+locale+('/'+page if page else ''), 'httpStatus':response.status,
                'language':document.lang, 'localizedMetadata':True}

    def anonymous_account(self, locale):
        response = self.client.request('/'+locale+'/account')
        self.require(response.status == 200 and urllib.parse.urlsplit(response.url).path == '/'+locale+'/login')
        return dict(redirectedToLogin=True)

    def not_found(self, locale, path=None):
        path = path or '/'+locale+'/portal-qa-missing-page'
        response = self.client.request(path)
        document = Document(response.body.decode('utf-8'))
        self.require(response.status == 404, 'not_found_http_status', expected=404, actual=response.status)
        self.require(document.lang == locale, 'not_found_language', expected=locale,
                     actual=document.lang if document.lang in ('en','ru') else 'other')
        self.require('404' in document.visible, 'not_found_content_missing', expected=True,
                     actual='404' in document.visible)
        self.require(not VISIBLE_KEY.search(document.visible), 'not_found_visible_translation_key',
                     expected=False, actual=bool(VISIBLE_KEY.search(document.visible)))
        if locale == 'ru':
            self.require(bool(CYRILLIC.search(document.visible)))
        return dict(path=path, httpStatus=404, language=document.lang, visibleLocalizedHtml=True)

    def known_news_detail(self, locale):
        response = self.client.request('/api/news?locale='+locale+'&limit=1')
        self.require(response.status == 200, 'news_listing_status', expected=200, actual=response.status)
        payload = response.json()
        posts = payload if isinstance(payload, list) else payload.get('posts', payload.get('news', []))
        self.require(isinstance(posts, list) and bool(posts), 'published_news_missing', expected=True,
                     actual=isinstance(posts, list) and bool(posts))
        post = posts[0]
        slug = post.get('slug') if isinstance(post, dict) else None
        self.require(isinstance(slug, str) and bool(re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', slug)),
                     'news_slug_invalid', expected=True,
                     actual=isinstance(slug, str) and bool(re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', slug)))
        return self.route(locale, 'news/'+slug)

    def missing_news_detail(self, locale):
        slug = 'portal-qa-missing-news-'+secrets.token_hex(6)
        api = self.client.request('/api/news/'+slug+'?locale='+locale)
        self.require(api.status == 404, 'missing_news_api_status', expected=404, actual=api.status)
        result = self.not_found(locale, '/'+locale+'/news/'+slug)
        result['newsApiHttpStatus'] = api.status
        return result

    def localization_routing(self):
        automatic = Client(self.base_url).request('/', language='ru-RU,ru;q=0.9,en;q=0.5')
        self.require(urllib.parse.urlsplit(automatic.url).path == '/ru')
        manual = Client(self.base_url).request('/', language='ru-RU', cookie='tionline_locale=en')
        self.require(urllib.parse.urlsplit(manual.url).path == '/en')
        return dict(browserLocaleDetected=True, manualCookieHasPriority=True,
                    browserSelectorPersistence='requires_browser_check')

    def csrf(self):
        token = self.client.session()['csrfToken']
        missing = self.client.request('/api/auth/register', method='POST', body={}, origin=self.base_url)
        wrong_origin = self.client.request('/api/auth/register', method='POST', body={}, token=token,
                                          origin='https://invalid.example')
        absent_origin = self.client.request('/api/auth/register', method='POST', body={}, token=token)
        self.require(all(response.status == 403 for response in (missing, wrong_origin, absent_origin)))
        return dict(missingCsrf=403, foreignOrigin=403, missingOrigin=403,
                    registrationRateBudgetConsumed=False)

    def public_apis(self):
        status = self.client.request('/api/server/status')
        self.require(status.status == 200, 'public_status_http_status', expected=200, actual=status.status)
        value = status.json()
        self.require(value.get('status') in ('online', 'offline', 'maintenance'))
        count = value.get('playersOnline')
        self.require(count is None or type(count) is int and count >= 0)
        self.require(value.get('mocked') is False)
        version = self.client.request('/api/client/version')
        self.require(version.status == 200, 'client_version_http_status', expected=200, actual=version.status)
        data = version.json()
        self.require(all(key in data for key in ('gameVersion','launcherVersion','downloadUrl','launcherUrl')))
        russian_news = self.client.request('/api/news?locale=ru')
        self.require(russian_news.status == 200, 'russian_news_http_status', expected=200, actual=russian_news.status)
        news = russian_news.json()
        posts = news if isinstance(news, list) else news.get('posts', news.get('news', []))
        self.require(isinstance(posts, list))
        cyrillic = any(CYRILLIC.search(json.dumps(post, ensure_ascii=False)) for post in posts)
        self.require(not posts or cyrillic)
        return dict(status=value['status'], playersOnline=count, mocked=False,
                    russianNewsPosts=len(posts), cyrillicNewsObserved=cyrillic,
                    cyrillicNewsConclusion='verified' if cyrillic else 'no_published_posts')

    def cookies(self, response):
        headers = response.headers.get_all('Set-Cookie', [])
        session = next((value for value in headers if value.startswith('__Host-tio_session=')), '')
        lowered = session.lower()
        for reason, valid in [('host_session_cookie_missing', bool(session)),
                              ('session_cookie_not_secure', 'secure' in lowered),
                              ('session_cookie_not_httponly', 'httponly' in lowered),
                              ('session_cookie_samesite', 'samesite=lax' in lowered),
                              ('session_cookie_path', 'path=/' in lowered),
                              ('session_cookie_has_domain', 'domain=' not in lowered)]:
            self.require(valid, reason, expected=True, actual=valid)
        return dict(secure=True, httpOnly=True, sameSite='Lax', hostPrefix=True)

    def create_fixture(self):
        username = 'webqa_'+secrets.token_hex(5)
        fixture = dict(username=username, email=username+'@example.invalid',
                       password=secrets.token_urlsafe(24)+'-Qa7')
        response = self.client.mutate('/api/auth/register', dict(fixture, confirmPassword=fixture['password']))
        self.require(response.status == 201)
        self.fixtures.append(fixture)
        self.report['createdFixtures'] = len(self.fixtures)
        self.require(response.json().get('user', {}).get('username') == username)
        cookie_detail = self.cookies(response)
        session = self.client.session()
        self.require(session.get('user', {}).get('username') == username)
        return dict(created=True, automaticSession=True, **cookie_detail)

    def duplicate_and_invalid_registration(self):
        fixture = self.fixtures[0]
        duplicate_username = self.client.mutate('/api/auth/register',
            dict(fixture, confirmPassword=fixture['password']))
        duplicate_email = self.client.mutate('/api/auth/register',
            dict(fixture, username=fixture['username']+'_dupe', confirmPassword=fixture['password']))
        weak = self.client.mutate('/api/auth/register',
            dict(fixture, username=fixture['username']+'_weak', email='weak_'+fixture['email'],
                 password='short', confirmPassword='short'))
        self.require(duplicate_username.status == 409, 'duplicate_username_status', expected=409, actual=duplicate_username.status)
        self.require(duplicate_email.status == 409, 'duplicate_email_status', expected=409, actual=duplicate_email.status)
        self.require(weak.status == 400, 'weak_password_status', expected=400, actual=weak.status)
        self.require(duplicate_username.json().get('error') == 'auth.errors.username_exists')
        self.require(duplicate_email.json().get('error') == 'auth.errors.email_exists')
        return dict(duplicateUsername=409, duplicateEmail=409, weakPassword=400,
                    registrationRequests=3)

    def login_and_authorization(self):
        fixture = self.fixtures[0]
        logout = self.client.mutate('/api/auth/logout', {})
        self.require(logout.status == 200, 'pre_login_logout_status', expected=200, actual=logout.status)
        self.require(self.client.session().get('user') is None)
        wrong = self.client.mutate('/api/auth/login',
            dict(username=fixture['username'], password='wrong-test-password-999'))
        self.require(wrong.status == 401, 'wrong_login_status', expected=401, actual=wrong.status)
        login = self.client.mutate('/api/auth/login',
            dict(username=fixture['username'], password=fixture['password']))
        self.require(login.status == 200, 'correct_login_status', expected=200, actual=login.status)
        self.cookies(login)
        self.require(self.client.session().get('user', {}).get('username') == fixture['username'])
        for locale in ('en', 'ru'):
            account = self.client.request('/'+locale+'/account')
            document = Document(account.body.decode('utf-8'))
            self.require(account.status == 200, 'account_route_status_'+locale, expected=200, actual=account.status)
            self.require(document.lang == locale, 'account_language_'+locale, expected=locale,
                         actual=document.lang if document.lang in ('en','ru') else 'other')
            self.require(fixture['username'] in document.visible, 'account_identity_hidden_'+locale,
                         expected=True, actual=fixture['username'] in document.visible)
            self.require(not VISIBLE_KEY.search(document.visible), 'account_visible_translation_key_'+locale,
                         expected=False, actual=bool(VISIBLE_KEY.search(document.visible)))
        denied = self.client.mutate('/api/admin/news', {})
        self.require(denied.status == 403, 'normal_user_admin_api_status', expected=403, actual=denied.status)
        for locale in ('en', 'ru'):
            page = self.client.request('/'+locale+'/admin')
            document = Document(page.body.decode('utf-8'))
            restricted = (page.status in (403, 404) or '/login' in page.url
                or page.status == 200 and '403' in document.visible
                and 'admin-panel' not in document.classes
                and not VISIBLE_KEY.search(document.visible))
            self.require(restricted, 'normal_user_admin_page_restriction_'+locale,
                         expected=True, actual=restricted)
        return dict(wrongPassword=401, validLogin=True, accountLanguages=['en','ru'],
                    normalUserAdminApi=403)

    def logout_existing_fixture(self):
        response = self.client.mutate('/api/auth/logout', {})
        self.require(response.status == 200, 'final_logout_status', expected=200, actual=response.status)
        self.require(self.client.session().get('user') is None, 'session_survives_logout', expected=False,
                     actual=self.client.session().get('user') is not None)
        return dict(loggedOut=True)

    def password_and_logout(self):
        fixture = self.fixtures[0]
        changed = secrets.token_urlsafe(24)+'-Qb8'
        response = self.client.mutate('/api/auth/password', dict(currentPassword=fixture['password'],
                                     newPassword=changed, confirmPassword=changed))
        self.require(response.status == 200, 'password_change_status', expected=200, actual=response.status)
        old_password = fixture['password']
        fixture['password'] = changed
        self.require(self.client.mutate('/api/auth/logout', {}).status == 200)
        rejected = self.client.mutate('/api/auth/login', dict(username=fixture['username'], password=old_password))
        self.require(rejected.status == 401, 'old_password_login_status', expected=401, actual=rejected.status)
        accepted = self.client.mutate('/api/auth/login', dict(username=fixture['username'], password=changed))
        self.require(accepted.status == 200, 'new_password_login_status', expected=200, actual=accepted.status)
        self.cookies(accepted)
        self.require(self.client.mutate('/api/auth/logout', {}).status == 200)
        self.require(self.client.session().get('user') is None)
        return dict(changed=True, oldPasswordRejected=401, newPasswordAccepted=True, loggedOut=True)

    def game_probe(self, host, login_port, session_port):
        # Reuse codecs and fixture helpers already tested against the emulator.
        import socket
        from types import SimpleNamespace
        sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
        from test_multi_account import MultiAccountTests
        case = MultiAccountTests()
        case.config = SimpleNamespace(game_port=login_port, session_port=session_port)
        case.clients = []
        def connect(port):
            connection = socket.create_connection((host, port), timeout=15)
            case.clients.append(connection)
            return connection
        case.connect = connect
        try:
            peers = []
            for fixture in self.fixtures:
                peer = case.handoff(case.begin(fixture['username'], fixture['password']))
                self.require(case.character_screen(peer) == ())
                case.ping(peer)
                peers.append(peer)
            deadline = time.monotonic()+25
            observed = None
            while time.monotonic() < deadline:
                response = self.client.request('/api/server/status')
                if response.status == 200:
                    status = response.json()
                    count = status.get('playersOnline')
                    if type(count) is int and count >= len(peers):
                        observed = count
                        break
                for peer in peers:
                    case.ping(peer)
                time.sleep(2)
            self.require(observed is not None)
            return dict(authenticatedFixtureAccounts=len(peers), emptyCharacterSelection=True,
                        realPopulationObserved=observed, graphicalClients=False,
                        protocol='legacy ORANGE, no gameplay or character creation')
        finally:
            for connection in case.clients:
                connection.close()

    def run_readonly(self):
        for locale in ('en', 'ru'):
            for page in ('', 'register', 'login', 'download', 'faq', 'news', 'changelog',
                         'community', 'how-to-play', 'maintenance'):
                self.check('route_'+locale+'_'+(page or 'home'),
                           lambda locale=locale, page=page: self.route(locale, page))
            self.check('anonymous_account_'+locale, lambda locale=locale: self.anonymous_account(locale))
            self.check('not_found_'+locale, lambda locale=locale: self.not_found(locale))
            self.check('known_news_detail_'+locale, lambda locale=locale: self.known_news_detail(locale))
            self.check('missing_news_detail_'+locale, lambda locale=locale: self.missing_news_detail(locale))
        self.check('not_found_unknown_dotted_ru', lambda: self.not_found('ru', '/ru/outpost.unknown'))
        self.check('locale_routing_and_cookie_precedence', self.localization_routing)
        self.check('csrf_and_origin_enforcement', self.csrf)
        self.check('public_status_download_and_cyrillic_news', self.public_apis)


def credentials_path(value, *, existing=False):
    path = Path(value).expanduser().resolve()
    allowed = [ROOT/'data']
    if os.name != 'nt':
        allowed.append(Path('/root'))
    if not any(path.is_relative_to(root.resolve()) for root in allowed):
        raise ValueError('Credentials path must be under ignored workspace data/ or /root')
    if existing and not path.is_file():
        raise ValueError('Existing credentials file is unavailable')
    if not existing and path.exists():
        raise ValueError('Credentials output already exists; choose a fresh explicit path')
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='https://185.184.42.88')
    parser.add_argument('--report', type=Path, default=ROOT/'reports/portal/hosted-verification.json')
    parser.add_argument('--allow-create', action='store_true', help='Explicitly allow owned webqa_* fixture creation')
    parser.add_argument('--accounts', type=int, choices=(1, 2), default=1)
    parser.add_argument('--credentials-file', help='Optional protected output in ignored data/ or /root; no credentials otherwise saved')
    parser.add_argument('--existing-credentials-file', help='Reuse explicitly saved owned QA fixtures for auth checks; creates no accounts and does not change passwords')
    parser.add_argument('--auth-only', action='store_true', help='With existing credentials, rerun only login/account/admin/logout checks')
    parser.add_argument('--game-probe', action='store_true', help='Authenticate only owned fixtures with real game TCP; no gameplay')
    parser.add_argument('--game-host', help='Defaults to HTTPS hostname')
    parser.add_argument('--login-port', type=int, default=28512)
    parser.add_argument('--session-port', type=int, default=28513)
    args = parser.parse_args()
    parsed = urllib.parse.urlsplit(args.base_url)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
        parser.error('--base-url must be a trusted HTTPS origin')
    if (args.game_probe or args.credentials_file or args.accounts == 2) and not (args.allow_create or args.existing_credentials_file):
        parser.error('Fixture creation and credential output require --allow-create')
    if args.existing_credentials_file and (args.allow_create or args.credentials_file):
        parser.error('Existing-fixture checks cannot be combined with creation or credential output')
    if args.auth_only and not args.existing_credentials_file:
        parser.error('--auth-only requires --existing-credentials-file')
    try:
        output = credentials_path(args.credentials_file) if args.credentials_file else None
        existing = credentials_path(args.existing_credentials_file, existing=True) if args.existing_credentials_file else None
    except ValueError as error:
        parser.error(str(error))
    if output == args.report.resolve():
        parser.error('Report and credential output must be different files')
    verifier = Verifier(args.base_url.rstrip('/'), args.report.resolve())
    verifier.report['mutationsAuthorized'] = args.allow_create
    if not args.auth_only:
        verifier.run_readonly()
    try:
        if existing:
            data = json.loads(existing.read_text(encoding='utf-8'))
            if data.get('baseUrl') != verifier.base_url or not isinstance(data.get('fixtures'), list) or not 1 <= len(data['fixtures']) <= 2:
                raise ValueError('Existing QA credentials do not match this portal')
            for fixture in data['fixtures']:
                if (not isinstance(fixture, dict) or not isinstance(fixture.get('username'), str)
                        or not re.fullmatch(r'webqa_[a-z0-9_]{3,26}', fixture['username'])
                        or not isinstance(fixture.get('password'), str)
                        or not re.fullmatch(r'[\x21-\x7e]{12,64}', fixture['password'])):
                    raise ValueError('Existing credentials are not owned portal QA fixtures')
            verifier.fixtures = data['fixtures']
            verifier.report['existingFixturesUsed'] = len(verifier.fixtures)
            verifier.check('login_account_and_admin_authorization', verifier.login_and_authorization)
            verifier.check('existing_fixture_final_logout', verifier.logout_existing_fixture)
            if args.game_probe:
                verifier.check('real_game_account_authentication_and_population',
                    lambda: verifier.game_probe(args.game_host or parsed.hostname, args.login_port, args.session_port))
        if args.allow_create:
            for index in range(args.accounts):
                verifier.check('register_owned_fixture_'+str(index+1), verifier.create_fixture)
                if len(verifier.fixtures) != index+1:
                    break
            if verifier.fixtures:
                verifier.check('duplicate_username_email_and_invalid_password', verifier.duplicate_and_invalid_registration)
                verifier.check('login_account_and_admin_authorization', verifier.login_and_authorization)
                verifier.check('password_change_and_logout', verifier.password_and_logout)
                if args.game_probe:
                    verifier.check('real_game_account_authentication_and_population',
                        lambda: verifier.game_probe(args.game_host or parsed.hostname, args.login_port, args.session_port))
    finally:
        if output and verifier.fixtures:
            output.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                json.dump(dict(baseUrl=verifier.base_url, fixtures=verifier.fixtures), stream, indent=2)
                stream.write('\n')
            os.chmod(output, 0o600)
            verifier.report['credentialsSaved'] = True
        verifier.report['finishedAt'] = datetime.now(timezone.utc).isoformat()
        verifier.save_report()
    checks = verifier.report['checks']
    print(json.dumps(dict(passed=verifier.report['passed'], passedChecks=sum(check['passed'] for check in checks),
                         totalChecks=len(checks), createdFixtures=verifier.report['createdFixtures'],
                         graphicalClientValidation=False, report=str(verifier.report_path))))
    return 0 if verifier.report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
