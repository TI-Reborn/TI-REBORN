"""Read-only HTTP SEO audit; stores public metadata, never cookies or accounts."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
from pathlib import Path
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = ''; self.h1 = []; self.meta = {}; self.links = []
        self.structured = []; self.assets = []; self.lang = ''; self.capture = None; self.buffer = ''

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'html': self.lang = a.get('lang', '')
        if tag == 'meta': self.meta[a.get('name', a.get('property', ''))] = a.get('content', '')
        if tag == 'link': self.links.append(a)
        if tag in ('img', 'script') and a.get('src', '').startswith('/'):
            self.assets.append(a['src'])
        if tag in ('title', 'h1') or (tag == 'script' and a.get('type') == 'application/ld+json'):
            self.capture = tag; self.buffer = ''

    def handle_data(self, data):
        if self.capture: self.buffer += data

    def handle_endtag(self, tag):
        if self.capture != tag: return
        if tag == 'title': self.title = self.buffer
        if tag == 'h1': self.h1.append(self.buffer)
        if tag == 'script': self.structured.append(json.loads(self.buffer))
        self.capture = None


def fetch(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'TI-Reborn-SEO-Verification/1.0'})
    try:
        response = urllib.request.urlopen(request, timeout=25)
    except urllib.error.HTTPError as error: response = error
    except Exception as error: return {'url': url, 'error': type(error).__name__}
    with response:
        body = response.read().decode('utf-8', errors='replace')
        result = dict(url=url, final_url=response.url, status=response.status,
                      content_type=response.headers.get('Content-Type'), x_robots=response.headers.get('X-Robots-Tag'))
        if 'text/html' in result['content_type']:
            page = Page(); page.feed(body)
            result.update(title=page.title, description=page.meta.get('description'), robots=page.meta.get('robots'),
                          canonical=next((a.get('href') for a in page.links if a.get('rel') == 'canonical'), None),
                          alternates={a['hreflang']: a.get('href') for a in page.links if 'hreflang' in a},
                          lang=page.lang, h1=page.h1, structured=page.structured, assets=sorted(set(page.assets)),
                          og_title=page.meta.get('og:title'), og_url=page.meta.get('og:url'))
        else: result['body'] = body
        return result


def audit(origin):
    paths = ['', '/robots.txt', '/sitemap.xml'] + [f'/{locale}{suffix}' for locale in ('en', 'ru') for suffix in
        ('', '/download', '/how-to-play', '/news', '/community', '/faq', '/changelog', '/privacy', '/terms',
         '/login', '/register', '/claim-existing', '/account', '/admin', '/bank', '/clan', '/city', '/services',
         '/ratings', '/assault', '/verify-email', '/password-reset', '/maintenance', '/seo-missing-page')]
    with ThreadPoolExecutor(max_workers=3) as pool: rows = list(pool.map(fetch, [origin + p for p in paths]))
    xml = next(row for row in rows if row['url'].endswith('/sitemap.xml'))
    if xml.get('status') == 200:
        root = ET.fromstring(xml['body'])
        urls = [node.text for node in root.findall('{*}url/{*}loc')]
        with ThreadPoolExecutor(max_workers=3) as pool: articles = list(pool.map(fetch, [url.replace('https://ti-reborn.com', origin) for url in urls if '/news/' in url]))
        rows.extend(articles)
    return {'created_utc': datetime.now(timezone.utc).isoformat(), 'origin': origin, 'pages': rows}


def check(report):
    origin = 'https://ti-reborn.com'; pages = report['pages']; failures = []
    for row in pages:
        path = row['url'].removeprefix(report['origin'])
        if path.endswith('seo-missing-page'):
            if row.get('status') != 404: failures.append(path + ': expected 404')
            continue
        if row.get('status') != 200: failures.append(path + ': request failed'); continue
        if 'title' not in row: continue
        public = path in [f'/{locale}{suffix}' for locale in ('en','ru') for suffix in ('','/download','/how-to-play','/news','/community','/faq','/changelog','/privacy','/terms')] or '/news/' in path
        if public:
            for valid, message in [(bool(row['description']), 'description'), (len(row['h1']) == 1, 'H1'),
                                   (row['canonical'] == origin + path, 'canonical'), ('noindex' not in (row['robots'] or ''), 'indexable'),
                                   (all(k in row['alternates'] for k in ('en','ru','x-default')), 'hreflang')]:
                if not valid: failures.append(path + ': ' + message)
            if path in ('/en','/ru','/en/download','/ru/download') and 'Total Influence Online' not in row['title']:
                failures.append(path + ': game name missing from title')
            types = {node.get('@type') for data in row['structured'] for node in data.get('@graph', [data])}
            if path in ('/en', '/ru'):
                if not {'WebSite', 'VideoGame', 'WebPage'} <= types: failures.append(path + ': structured data')
                if 'TOTAL INFLUENCE ONLINE' not in row['h1'][0]: failures.append(path + ': game name missing from H1')
            if '/news/' in path and not {'NewsArticle', 'BreadcrumbList'} <= types: failures.append(path + ': news structured data')
        elif path != '' and 'noindex' not in (row['robots'] or ''): failures.append(path + ': expected noindex')
    robots = next(row for row in pages if row['url'].endswith('/robots.txt'))
    if f'Sitemap: {origin}/sitemap.xml' not in robots.get('body', ''): failures.append('robots: sitemap origin')
    sitemap = next(row for row in pages if row['url'].endswith('/sitemap.xml'))
    root = ET.fromstring(sitemap['body']); urls = [n.text for n in root.findall('{*}url/{*}loc')]
    for locale in ('en','ru'):
        for path in ('','/download','/how-to-play','/news','/community','/faq','/changelog','/privacy','/terms'):
            if origin + '/' + locale + path not in urls: failures.append('sitemap: missing ' + locale + path)
    if len(set(urls)) != len(urls): failures.append('sitemap duplicates')
    if any(not url.startswith(origin + '/') for url in urls): failures.append('sitemap origin')
    for node in root.findall('{*}url'):
        if len(node.findall('{http://www.w3.org/1999/xhtml}link')) < 2: failures.append('sitemap hreflang')
    report['failures'] = failures
    return failures


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--origin', default='https://ti-reborn.com')
    parser.add_argument('--report', type=Path, required=True); parser.add_argument('--check', action='store_true'); args = parser.parse_args()
    result = audit(args.origin.rstrip('/'))
    if args.check: check(result)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'pages': len(result['pages']), 'failures': result.get('failures'), 'report': str(args.report)}, ensure_ascii=False))
    if result.get('failures'): raise SystemExit(1)
