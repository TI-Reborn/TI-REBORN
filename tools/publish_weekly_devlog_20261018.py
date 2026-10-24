"""Publish one bilingual news record, preserving other CMS content and services."""
import argparse,base64,hashlib,json,re,subprocess,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.inspect_training_base_20261018 import SSH
OUT=ROOT/'reports/devlog-20261018'
REMOTE=r'''
import hashlib,json,os,subprocess
from pathlib import Path
backup=Path(request['backup']);assert backup.parent==Path('/root') and backup.name.startswith('tio-before-site-backups-')
assert (backup/'website.dump').stat().st_size>0 and (backup/'portal-code.tar.gz').stat().st_size>0
subprocess.run(['pg_restore','--list',str(backup/'website.dump')],stdout=subprocess.DEVNULL,check=True)
assert str(Path('/opt/tio-portal/current').resolve())==request['release']
status=lambda:{n:subprocess.check_output(['systemctl','show',n,'-p','MainPID','-p','ActiveState','-p','NRestarts'],text=True) for n in ('tio-portal','tio-server')}
before=status();assert all('ActiveState=active' in s for s in before.values())
pg=['runuser','-u','postgres','--','psql','-X','-q','-tA','-v','ON_ERROR_STOP=1','-d','tionline_web']
sql=request['sql'];(backup/'weekly-devlog-publication.sql').write_text(sql)
run=subprocess.run(pg,input=sql,text=True,capture_output=True,timeout=35)
if run.returncode:
 (backup/'weekly-devlog-private-error.log').write_text(run.stderr)
 raise RuntimeError('CMS transaction failed; rolled back. Diagnostics remain in private remote backup.')
result=json.loads(run.stdout.strip());assert result['slug']==request['slug'] and result['translations']==2
assert status()==before
result.update(published=True,services_restarted=False,backup=str(backup),portal_release_unchanged=True,payload_sha256=request['payload_sha256'],other_news_preserved=True,user_tables_written=False,game_database_written=False)
(backup/'weekly-devlog-publication.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result))
'''

def payload():
 return dict(slug='devlog-2026-10-12-18',coverImage='/images/wasteland.webp',published=True,
  ru=dict(title='Девлог 12–18 октября: Training Base, обмен и улучшения боёв',description='Итоги недели: тренировочные базы без расписания, список групп и вход, прямой обмен, самостоятельные боты, кредиты за AI-бои, исправления магазина, лаунчера и серверных задержек.',content=(OUT/'devlog.ru.txt').read_text(encoding='utf-8').strip()),
  en=dict(title='Devlog, 12–18 October: Training Base, trading and battle improvements',description='This week: always-open Training Bases, working group lists and joining, direct player trading, more capable bots, AI credit rewards, shop fixes and launcher and server improvements.',content=(OUT/'devlog.en.txt').read_text(encoding='utf-8').strip()))

def main():
 parser=argparse.ArgumentParser();parser.add_argument('mode',choices=('prepare','publish'));args=parser.parse_args()
 item=payload()
 assert re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',item['slug']) and len(item['slug'])<=100
 for locale in ('ru','en'):
  assert 0<len(item[locale]['title'])<=160 and 0<len(item[locale]['description'])<=400 and 0<len(item[locale]['content'])<=50000
  assert '<' not in item[locale]['content'] and 'password' not in item[locale]['content'].lower()
  assert not any(x in item[locale]['content'] for x in ('/root/','185.184.42.88','qtb772dc6ea','API_KEY'))
 raw=(json.dumps(item,ensure_ascii=False,indent=2)+'\n').encode();target=OUT/'article.json'
 if args.mode=='prepare':
  assert not target.exists();target.write_bytes(raw)
  proof=dict(payload_sha256=hashlib.sha256(raw).hexdigest(),slug=item['slug'],id=str(uuid.uuid4()),translation_ids={l:str(uuid.uuid4()) for l in ('ru','en')},locales=['ru','en'],characters={l:len(item[l]['content']) for l in ('ru','en')})
  (OUT/'prepared.json').write_text(json.dumps(proof,indent=2));print(json.dumps(proof));return
 proof=json.loads((OUT/'prepared.json').read_text());assert target.read_bytes()==raw and hashlib.sha256(raw).hexdigest()==proof['payload_sha256']
 assert not (OUT/'publication.json').exists()
 backup=json.loads((OUT/'backup.json').read_text(encoding='utf-8'));baseline=json.loads((OUT/'portal-baseline.json').read_text())
 assert backup['website_dump_structure_verified'] and backup['previous_portal_release']==baseline['release']
 # The JSON payload is encoded as data. No content is interpolated as SQL text.
 expression="convert_from(decode('"+base64.b64encode(raw).decode()+"','base64'),'UTF8')::jsonb"
 ids=json.dumps(sorted(p['id'] for p in baseline['news']['posts']))
 sql='''BEGIN;
SET LOCAL lock_timeout='10s';
DO $lock$ BEGIN PERFORM pg_advisory_xact_lock(20261018,1218); END $lock$;
LOCK TABLE "NewsPost","NewsTranslation" IN SHARE ROW EXCLUSIVE MODE;
CREATE TEMP TABLE original_posts AS SELECT * FROM "NewsPost";
CREATE TEMP TABLE original_translations AS SELECT * FROM "NewsTranslation";
DO $guard$ BEGIN
 IF (SELECT json_agg(id ORDER BY id)::text FROM "NewsPost")::jsonb <> IDS::jsonb THEN RAISE EXCEPTION 'News changed since inspection'; END IF;
 IF EXISTS(SELECT 1 FROM "NewsPost" WHERE slug='SLUG') THEN RAISE EXCEPTION 'Article already exists'; END IF;
END $guard$;
WITH input AS (SELECT PAYLOAD AS j)
INSERT INTO "NewsPost"(id,slug,"coverImage",published,"publishedAt","createdAt","updatedAt")
SELECT 'POSTID',j->>'slug',j->>'coverImage',true,now() AT TIME ZONE 'UTC',now() AT TIME ZONE 'UTC',now() AT TIME ZONE 'UTC' FROM input;
WITH input AS (SELECT PAYLOAD AS j)
INSERT INTO "NewsTranslation"(id,"newsPostId",locale,title,description,content)
SELECT CASE l.locale WHEN 'ru' THEN 'RUID' ELSE 'ENID' END,'POSTID',l.locale,j->l.locale->>'title',j->l.locale->>'description',j->l.locale->>'content' FROM input CROSS JOIN (VALUES('ru'),('en')) l(locale);
DO $guard$ BEGIN
 IF EXISTS((SELECT * FROM original_posts EXCEPT SELECT * FROM "NewsPost") UNION ALL (SELECT * FROM "NewsPost" WHERE id<>'POSTID' EXCEPT SELECT * FROM original_posts)) THEN RAISE EXCEPTION 'Other posts changed'; END IF;
 IF EXISTS((SELECT * FROM original_translations EXCEPT SELECT * FROM "NewsTranslation") UNION ALL (SELECT * FROM "NewsTranslation" WHERE "newsPostId"<>'POSTID' EXCEPT SELECT * FROM original_translations)) THEN RAISE EXCEPTION 'Other translations changed'; END IF;
 IF (SELECT count(*) FROM "NewsTranslation" WHERE "newsPostId"='POSTID')<>2 THEN RAISE EXCEPTION 'Incomplete translation'; END IF;
END $guard$;
COMMIT;
SELECT json_build_object('id',id,'slug',slug,'publishedAt',"publishedAt",'translations',(SELECT count(*) FROM "NewsTranslation" WHERE "newsPostId"='POSTID')) FROM "NewsPost" WHERE id='POSTID';
'''
 # IDs and slug are generated/validated above, baseline IDs are known UUIDs.
 assert all(str(uuid.UUID(p['id']))==p['id'] for p in baseline['news']['posts'])
 substitutions={'IDS':"'"+ids+"'",'SLUG':item['slug'],'POSTID':proof['id'],'RUID':proof['translation_ids']['ru'],'ENID':proof['translation_ids']['en'],'PAYLOAD':expression}
 for name,value in substitutions.items():sql=sql.replace(name,value)
 request=dict(backup=backup['backup'],release=baseline['release'],slug=item['slug'],sql=sql,payload_sha256=proof['payload_sha256'])
 result=subprocess.run(SSH+['python3 -'],input='request='+repr(request)+'\n'+REMOTE,capture_output=True,encoding='utf-8',timeout=90)
 if result.returncode:raise RuntimeError(result.stderr[-1200:])
 receipt=json.loads(result.stdout);(OUT/'publication.json').write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt))
if __name__=='__main__':main()
