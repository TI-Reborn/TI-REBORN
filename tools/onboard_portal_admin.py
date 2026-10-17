"""Link an explicitly authorized administrator through the public secure API.

The game account must already exist, its name must be reserved by the server,
and the operator supplies the real owner email. Never prints credentials.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import urllib.parse

from verify_portal_hosted import Client


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--username', required=True)
    parser.add_argument('--email', required=True)
    parser.add_argument('--password-file', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    origin = urllib.parse.urlsplit(args.base_url)
    if (origin.scheme != 'https' or not origin.hostname or origin.username or origin.password
            or origin.path not in ('', '/') or origin.query or origin.fragment):
        parser.error('Use a trusted HTTPS origin')
    if not re.fullmatch(r'[a-z0-9_]{3,32}', args.username):
        parser.error('Use the canonical game username')
    instructions = args.password_file.read_text(encoding='utf-8')
    passwords = re.findall(r'^Temporary (?:game )?password:\s*([^\s]+)\s*$', instructions, re.MULTILINE)
    if len(passwords) != 1 or not re.fullmatch(r'[!-~]{12,64}', passwords[0]):
        raise SystemExit('Protected password file has no unique compatible credential')
    client = Client(args.base_url.rstrip('/'))
    response = client.mutate('/api/auth/claim', {
        'username': args.username, 'email': args.email, 'password': passwords[0],
    })
    if response.status != 201:
        raise SystemExit(f'Administrator linking failed with HTTP {response.status}; no credential output')
    user = response.json().get('user', {})
    if user.get('username') != args.username or user.get('role') != 'ADMIN':
        raise SystemExit('Server did not confirm the requested administrator role')
    checks = {path: client.request(path).status for path in ('/api/admin/news', '/api/admin/settings')}
    if any(status != 200 for status in checks.values()):
        raise SystemExit('Administrator API verification failed')
    logout = client.mutate('/api/auth/logout', {})
    if logout.status != 200 or client.session().get('user') is not None:
        raise SystemExit('Administrator verification session did not close')
    report = {
        'verifiedAt': datetime.now(timezone.utc).isoformat(),
        'baseUrl': client.base_url, 'username': args.username,
        'websiteProfileCreated': True, 'emailLinked': user.get('email') == args.email.lower(),
        'role': 'ADMIN', 'adminApis': checks, 'verificationSessionClosed': True,
        'passwordPrinted': False, 'passed': True,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'passed': True, 'role': 'ADMIN', 'report': str(args.report)}))


if __name__ == '__main__':
    main()
