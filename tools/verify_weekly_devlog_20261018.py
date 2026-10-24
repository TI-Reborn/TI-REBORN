"""Check both live translations, listing, homepage and page metadata via HTTPS."""
import hashlib,html,json,sys,urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
OUT=ROOT/'reports/devlog-20261018';item=json.loads((OUT/'article.json').read_text(encoding='utf-8'))
ORIGIN='https://ti-reborn.com';slug=item['slug']
paths=['/'+l+'/news/'+slug for l in ('ru','en')]+['/api/news/'+slug+'?locale='+l for l in ('ru','en')]+['/api/news?locale='+l+'&limit=100' for l in ('ru','en')]+['/'+l for l in ('ru','en')]+['/'+l+'/news' for l in ('ru','en')]
def fetch(path):
 req=urllib.request.Request(ORIGIN+path,headers={'User-Agent':'Mozilla/5.0 (compatible; TIReborn-PublicationCheck/1.0)','Cache-Control':'no-cache'})
 with urllib.request.urlopen(req,timeout=30) as r:return path,dict(status=r.status,body=r.read().decode('utf-8'),url=r.url)
responses=dict(ThreadPoolExecutor(max_workers=3).map(fetch,paths));checks=[]
for locale in ('ru','en'):
 page=responses['/'+locale+'/news/'+slug];api=json.loads(responses['/api/news/'+slug+'?locale='+locale]['body'])['post']
 for field in ('title','description','content'):assert api[field]==item[locale][field],field
 assert api['slug']==slug and api['coverImage']==item['coverImage']
 body=page['body'];assert '<html lang="'+locale+'"' in body
 assert html.escape(item[locale]['title']) in body
 assert 'rel="canonical" href="'+ORIGIN+'/'+locale+'/news/'+slug+'"' in body
 assert 'NewsArticle' in body
 for paragraph in item[locale]['content'].split('\n\n'):assert html.escape(paragraph) in body
 listing=json.loads(responses['/api/news?locale='+locale+'&limit=100']['body'])['posts']
 assert listing[0]['slug']==slug and len(listing)==4
 for path in ('/'+locale,'/'+locale+'/news'):assert '/'+locale+'/news/'+slug in responses[path]['body']
 checks.append(dict(locale=locale,api_content_exact=True,all_paragraphs_in_html=True,canonical=True,structured_data=True,first_in_news=True,homepage_link=True))
from tools.inspect_training_base_20261018 import remote
baseline=json.loads((OUT/'portal-baseline.json').read_text())
state=remote('''import json,subprocess
from pathlib import Path
print(json.dumps(dict(release=str(Path('/opt/tio-portal/current').resolve()),services={n:subprocess.check_output(['systemctl','show',n,'-p','MainPID','-p','ActiveState','-p','NRestarts'],text=True) for n in ('tio-portal','tio-server')})))
''')
assert state['services']==baseline['services'] and state['release']==baseline['release']
report=dict(passed=True,checks=checks,services_unchanged=True,portal_release_unchanged=True,urls={l:ORIGIN+'/'+l+'/news/'+slug for l in ('ru','en')},responses={p:dict(status=v['status'],bytes=len(v['body'].encode())) for p,v in responses.items()})
(OUT/'https-verification.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
