"""Verify the public launcher through normal HTTPS without saving or executing it."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import urllib.request

URL = 'https://ti-reborn.com/downloads/TIO-Launcher.exe'
EXPECTED_SHA256 = '8a34ea68124eebfb6ded5f2c9d8c96dee85befb9eb99b5efb57d5dea708b4d52'
EXPECTED_BYTES = 118679712
OUTPUT = Path(__file__).resolve().parents[1] / 'reports/game-tls/public-https-download.json'


def main():
    hasher, size = hashlib.sha256(), 0
    request = urllib.request.Request(URL, headers={'Cache-Control': 'no-cache', 'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(request, timeout=45) as response:
        status, resolved = response.status, response.url
        content_length = response.headers.get('Content-Length')
        while chunk := response.read(1024 * 1024):
            size += len(chunk)
            if size > 200 * 1024 * 1024:
                raise ValueError('Unexpected public launcher size')
            hasher.update(chunk)
    report = dict(passed=status == 200 and size == EXPECTED_BYTES and hasher.hexdigest() == EXPECTED_SHA256,
        observed_utc=datetime.now(timezone.utc).isoformat(), url=URL, resolved_url=resolved,
        http_status=status, bytes=size, content_length=content_length, sha256=hasher.hexdigest(),
        https_chain_and_name_verified=True, downloaded_file_saved=False, downloaded_file_executed=False)
    OUTPUT.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
