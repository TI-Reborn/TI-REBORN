"""Check live CAPTCHA rejection and login with an existing owned QA fixture.

Does not solve a challenge, create accounts, send mail or change game data.
Use the fixture created by verify_hosted_email_registration.py.
The optional token check needs an unredacted response from an automatically
completed widget. Browser tooling may redact it; never submit that placeholder.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from verify_hosted_email_registration import Browser


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--automatic-token-file', type=Path,
                        help='Optional response from a widget that passed automatically; checks duplicate registration and replay only')
    args = parser.parse_args()
    if args.report.exists():
        parser.error('Preserve the previous CAPTCHA report')
    credentials = json.loads(args.fixture.read_text(encoding='utf-8'))
    report = {'created_utc': datetime.now(timezone.utc).isoformat(), 'passed': False,
              'manual_challenge_completed': False, 'new_account_creation_intended': False,
              'graphical_game_client_validated': False, 'checks': []}
    browser = Browser()
    try:
        register = {**credentials, 'confirmPassword': credentials['password'], 'locale': 'ru'}
        claim = {key: credentials[key] for key in ('username', 'password', 'email')}
        cases = [] if args.automatic_token_file else [('/api/auth/register', register), ('/api/auth/claim', claim)]
        for path, body in cases:
            status, _, result = browser.mutate(path, body)
            assert status == 400 and result == {'error': 'auth.errors.captcha_required'}
            report['checks'].append({'endpoint': path, 'token': 'absent', 'status': status,
                                     'error': result['error']})
            status, _, result = browser.mutate(path, {**body, 'turnstileToken': 'TIREBORN.INVALID.QA.RESPONSE'})
            assert status == 400 and result == {'error': 'auth.errors.captcha_failed'}
            report['checks'].append({'endpoint': path, 'token': 'invalid', 'status': status,
                                     'error': result['error']})
        if args.automatic_token_file:
            token = args.automatic_token_file.read_text(encoding='utf-8').strip()
            report['automatic_token_length'] = len(token)
            assert token.upper() not in ('[REDACTED]', '<REDACTED>', 'REDACTED')
            assert 1 <= len(token) <= 2048
            status, _, result = browser.mutate('/api/auth/register', {**register, 'turnstileToken': token})
            report['real_token_observation'] = {'status': status, 'error': result.get('error')}
            assert status == 409 and result == {'error': 'auth.errors.username_exists'}
            report['checks'].append({'endpoint': '/api/auth/register', 'token': 'automatic real widget response',
                                     'status': status, 'captcha_accepted_before_duplicate_account_rejection': True,
                                     'error': result['error']})
            status, _, result = browser.mutate('/api/auth/register', {**register, 'turnstileToken': token})
            assert status == 400 and result == {'error': 'auth.errors.captcha_failed'}
            report['checks'].append({'endpoint': '/api/auth/register', 'token': 'replayed real widget response',
                                     'status': status, 'error': result['error']})
        status, _, result = browser.mutate('/api/auth/login', {key: credentials[key] for key in ('username', 'password')})
        assert status == 200 and result['user']['status'] == 'ACTIVE'
        assert browser.session()['user']['status'] == 'ACTIVE'
        assert browser.mutate('/api/auth/logout', {})[0] == 200
        report['checks'].append({'endpoint': '/api/auth/login', 'status': status,
                                 'active_existing_account': True, 'captcha_required': False})
        status, _, health = browser.request('/api/health')
        assert status == 200 and health == {'status': 'ok', 'database': 'ready', 'gameBridge': 'ready'}
        report['checks'].append({'endpoint': '/api/health', 'status': status, 'response': health})
        report['passed'] = True
    except Exception as error:
        report['failure_type'] = type(error).__name__
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
