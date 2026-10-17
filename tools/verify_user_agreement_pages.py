"""Read public legal pages and confirm delivery of the accepted agreement.

Only GET requests are performed. HTTPS keeps normal certificate validation;
plain HTTP is accepted only for an owned loopback preview.
"""
import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import urllib.parse
import urllib.request


ROOT = Path(__file__).resolve().parents[1]


class LegalArticle(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.inside = False
        self.capture = None
        self.fragments = []
        self.paragraphs = []
        self.headings = []
        self.hrefs = []
        self.section_number = False
        self.metadata = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'article' and 'legal-page' in attrs.get('class', '').split():
            self.inside = True
        if tag == 'meta' and attrs.get('name') == 'description':
            self.metadata['description'] = attrs.get('content')
        if tag == 'link' and attrs.get('rel') == 'canonical':
            self.metadata['canonical'] = attrs.get('href')
        if tag == 'time':
            self.metadata['effective_date'] = attrs.get('datetime')
        if not self.inside:
            return
        if tag in ('h1', 'h2', 'p'):
            self.capture = tag
            self.fragments = []
        if self.capture == 'h2' and tag == 'span':
            self.section_number = True
        if tag == 'a':
            self.hrefs.append(attrs.get('href'))

    def handle_endtag(self, tag):
        if tag == 'span':
            self.section_number = False
        if self.capture == tag:
            value = ''.join(self.fragments)
            if tag == 'p':
                self.paragraphs.append(value)
            elif tag == 'h2':
                self.headings.append(value)
            else:
                self.metadata['h1'] = value
            self.capture = None
        if tag == 'article':
            self.inside = False

    def handle_data(self, data):
        if self.capture and not self.section_number:
            self.fragments.append(data)


def verify(base_url, folder, expected_sha256):
    origin = urllib.parse.urlsplit(base_url)
    if origin.scheme != 'https' and not (
        origin.scheme == 'http' and origin.hostname in {'127.0.0.1', 'localhost', '::1'}
    ):
        raise ValueError('Use verified HTTPS or an owned loopback preview')
    canonical_path = ROOT / 'web/src/lib/user-agreement.json'
    digest = hashlib.sha256(canonical_path.read_bytes()).hexdigest()
    if digest != expected_sha256:
        raise ValueError('Canonical agreement changed')
    canonical = json.loads(canonical_path.read_text(encoding='utf-8'))
    folder.mkdir(parents=True, exist_ok=False)
    results = []
    for locale in ('ru', 'en'):
        dictionary = json.loads((ROOT / 'web/src/locales' / (locale + '.json')).read_text(encoding='utf-8'))
        before = json.loads((ROOT / 'reports/user-agreement-20261012/portal-source-before' / (locale + '.json')).read_text(encoding='utf-8'))
        for page in ('terms', 'privacy', 'register'):
            url = f'{base_url.rstrip("/")}/{locale}/{page}'
            request = urllib.request.Request(url, headers={'User-Agent': 'TI-REBORN-Legal-Delivery-Check/1'})
            with urllib.request.urlopen(request, timeout=30) as response:
                html = response.read().decode('utf-8')
                status = response.status
            output = folder / f'{locale}-{page}.html'
            output.write_text(html, encoding='utf-8')
            article = LegalArticle()
            article.feed(html)
            if page == 'terms':
                content = canonical['locales'][locale]
                paragraphs = [canonical['project'], content['editionLabel'], content['intro']]
                paragraphs.extend(paragraph for section in content['sections'] for paragraph in section['paragraphs'])
                checks = {
                    'twelve_titles_exact': article.headings == [section['title'] for section in content['sections']] + [content['contactsLabel']],
                    'paragraphs_exact_once_in_article': article.paragraphs == paragraphs,
                    'title_exact': article.metadata.get('h1') == content['title'],
                    'metadata_description_exact': article.metadata.get('description') == content['intro'],
                    'canonical_url_exact': article.metadata.get('canonical') == f'https://ti-reborn.com/{locale}/terms',
                    'edition_date_exact': article.metadata.get('effective_date') == canonical['effectiveDate'],
                    'contacts_exact': article.hrefs == [canonical['contacts']['website'], canonical['contacts']['telegram']],
                }
            elif page == 'privacy':
                checks = {
                    'four_sections': len(article.headings) == 4,
                    'first_three_bodies_preserved': article.paragraphs[2:5] == [before[f'privacy.{i}.body'] for i in range(1, 4)],
                    'provider_description_current': article.paragraphs[5:] == [dictionary['privacy.4.body']],
                }
            else:
                checks = {
                    'signup_copy_current': dictionary['auth.agreement'] in html,
                    'terms_link_preserved': f'href="/{locale}/terms"' in html,
                    'privacy_link_preserved': f'href="/{locale}/privacy"' in html,
                }
            results.append({'locale': locale, 'page': page, 'http_status': status, 'checks': checks,
                            'html_path': str(output), 'html_sha256': hashlib.sha256(html.encode('utf-8')).hexdigest()})
    result = {'canonical_sha256': digest, 'base_url': base_url, 'read_only_gets': True,
              'post_actions_performed': False, 'tls_verification_disabled': False,
              'pages': results, 'all_passed': all(all(row['checks'].values()) for row in results)}
    (folder / 'checks.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='https://ti-reborn.com')
    parser.add_argument('--report-folder', required=True, type=Path)
    parser.add_argument('--canonical-sha256', required=True)
    args = parser.parse_args()
    result = verify(args.base_url, args.report_folder, args.canonical_sha256)
    print(json.dumps({'all_passed': result['all_passed'], 'pages': len(result['pages']),
                      'canonical_sha256': result['canonical_sha256'], 'report': str(args.report_folder / 'checks.json')}))
    if not result['all_passed']:
        raise SystemExit('Delivered legal text differs; see the saved checks')


if __name__ == '__main__':
    main()
