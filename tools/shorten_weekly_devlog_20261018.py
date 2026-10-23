"""Edit only the existing weekly article translations after an online CMS backup."""
import base64,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.inspect_training_base_20261018 import SSH
OUT=ROOT/'reports/devlog-20261018-short'
before=json.loads((OUT/'before.json').read_text(encoding='utf-8'))
item=json.loads((OUT/'article.json').read_text(encoding='utf-8'))
identity='31846bb0-fc11-4f9f-bde1-ebe1bb9c1d99'
assert before['ru']['id']==before['en']['id']==identity
assert not (OUT/'publication.json').exists()
expected={l:{k:before[l][k] for k in ('title','description','content')} for l in ('ru','en')}
updated={l:item[l] for l in ('ru','en')}
def sql_json(value):
 return "convert_from(decode('"+base64.b64encode(json.dumps(value,ensure_ascii=False).encode()).decode()+"','base64'),'UTF8')::jsonb"
for l in ('ru','en'):
 assert 'gold' not in json.dumps(updated[l],ensure_ascii=False).lower()
 assert len(updated[l]['content'])<len(expected[l]['content'])*0.6
sql='''BEGIN;
SET LOCAL lock_timeout='10s';
LOCK TABLE "NewsPost","NewsTranslation" IN SHARE ROW EXCLUSIVE MODE;
CREATE TEMP TABLE old_posts AS SELECT * FROM "NewsPost";
CREATE TEMP TABLE old_translations AS SELECT * FROM "NewsTranslation";
DO $guard$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM "NewsPost" WHERE id='IDENTITY' AND slug='devlog-2026-10-12-18' AND published) THEN RAISE EXCEPTION 'Article changed'; END IF;
 IF (SELECT jsonb_object_agg(locale,jsonb_build_object('title',title,'description',description,'content',content)) FROM "NewsTranslation" WHERE "newsPostId"='IDENTITY') IS DISTINCT FROM EXPECTED THEN RAISE EXCEPTION 'Article edited concurrently'; END IF;
END $guard$;
WITH input AS (SELECT UPDATED AS j)
UPDATE "NewsTranslation" t SET title=j->t.locale->>'title',description=j->t.locale->>'description',content=j->t.locale->>'content' FROM input WHERE t."newsPostId"='IDENTITY' AND t.locale IN ('ru','en');
UPDATE "NewsPost" SET "updatedAt"=now() AT TIME ZONE 'UTC' WHERE id='IDENTITY';
DO $guard$ BEGIN
 IF EXISTS((SELECT * FROM old_translations WHERE "newsPostId"<>'IDENTITY' EXCEPT SELECT * FROM "NewsTranslation" WHERE "newsPostId"<>'IDENTITY') UNION ALL (SELECT * FROM "NewsTranslation" WHERE "newsPostId"<>'IDENTITY' EXCEPT SELECT * FROM old_translations WHERE "newsPostId"<>'IDENTITY')) THEN RAISE EXCEPTION 'Other translations changed'; END IF;
 IF EXISTS((SELECT to_jsonb(p)-'updatedAt' FROM old_posts p EXCEPT SELECT to_jsonb(p)-'updatedAt' FROM "NewsPost" p) UNION ALL (SELECT to_jsonb(p)-'updatedAt' FROM "NewsPost" p EXCEPT SELECT to_jsonb(p)-'updatedAt' FROM old_posts p)) THEN RAISE EXCEPTION 'Post metadata changed'; END IF;
 IF (SELECT count(*) FROM "NewsTranslation")<>(SELECT count(*) FROM old_translations) THEN RAISE EXCEPTION 'Translation count changed'; END IF;
END $guard$;
COMMIT;
SELECT json_build_object('id',id,'slug',slug,'publishedAt',"publishedAt",'updatedAt',"updatedAt") FROM "NewsPost" WHERE id='IDENTITY';
'''.replace('IDENTITY',identity).replace('EXPECTED',sql_json(expected)).replace('UPDATED',sql_json(updated))
REMOTE=r'''
import json,os,subprocess,tempfile
from pathlib import Path
os.umask(0o077)
status=lambda:{n:subprocess.check_output(['systemctl','show',n,'-p','MainPID','-p','NRestarts','-p','ActiveState'],text=True) for n in ('tio-portal','tio-server')}
before=status();assert all('ActiveState=active' in s for s in before.values())
folder=Path(tempfile.mkdtemp(prefix='tio-before-devlog-edit-',dir='/root'))
with (folder/'website.dump').open('xb') as out:subprocess.run(['runuser','-u','postgres','--','pg_dump','--format=custom','--dbname=tionline_web'],stdout=out,check=True)
subprocess.run(['pg_restore','--list',str(folder/'website.dump')],stdout=subprocess.DEVNULL,check=True)
(folder/'article-before.json').write_text(json.dumps(request['before'],ensure_ascii=False,indent=2))
(folder/'article-after.json').write_text(json.dumps(request['after'],ensure_ascii=False,indent=2))
(folder/'edit.sql').write_text(request['sql'])
run=subprocess.run(['runuser','-u','postgres','--','psql','-X','-q','-tA','-v','ON_ERROR_STOP=1','-d','tionline_web'],input=request['sql'],capture_output=True,text=True,timeout=30)
if run.returncode:
 (folder/'private-error.log').write_text(run.stderr)
 raise RuntimeError('CMS edit rolled back; diagnostics retained in private backup')
result=json.loads(run.stdout.strip());assert status()==before
result.update(published=True,backup=str(folder),services_unchanged=True,other_articles_preserved=True,published_date_preserved=True)
(folder/'receipt.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
'''
request=dict(before=before,after=item,sql=sql)
r=subprocess.run(SSH+['python3 -'],input='request='+repr(request)+'\n'+REMOTE,capture_output=True,encoding='utf-8',timeout=90)
if r.returncode:raise RuntimeError(r.stderr[-1200:])
result=json.loads(r.stdout);(OUT/'publication.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
