"""Owned website-only fixture; actual HTTP expiry, multi-tab lease and menu QA.

Run as root on the hosting server. No ordinary user or game account is touched.
"""
import argparse,hashlib,http.cookiejar,json,secrets,subprocess,time,urllib.request,urllib.error,uuid

def sql(statement):
 return subprocess.check_output(['runuser','-u','postgres','--','psql','-X','-t','-A','-d','tionline_web','-c',statement],text=True).strip()

def run(base,seconds):
 name='qt'+secrets.token_hex(4)+'a';uid=str(uuid.uuid4());tokens=[secrets.token_urlsafe(32) for _ in range(2)];csrf=secrets.token_urlsafe(32)
 ids=[str(uuid.uuid4()) for _ in tokens];hashes=[hashlib.sha256(t.encode()).hexdigest() for t in tokens]
 fingerprint=lambda:sql('SELECT md5(coalesce(string_agg(row_to_json(u)::text,\'\' ORDER BY id),\'\')) FROM "User" u WHERE id<>\''+uid+'\'')
 before=fingerprint();checks=[]
 def request(path,token=0,method='GET',origin=None,valid_csrf=True):
  headers={'Cookie':'__Host-tio_session='+tokens[token]}
  if method=='POST':headers.update({'Origin':origin or 'https://ti-reborn.com','X-CSRF-Token':csrf if valid_csrf else 'invalid'})
  req=urllib.request.Request(base+path,method=method,headers=headers,data=b'' if method=='POST' else None)
  try:
   with urllib.request.urlopen(req,timeout=20) as r:return r.status,r.read()
  except urllib.error.HTTPError as r:return r.code,r.read()
 def heartbeat(token=0):
  status,body=request('/api/auth/presence',token,'POST');assert status==200,status
  remaining=(__import__('datetime').datetime.fromisoformat(json.loads(body)['expiresAt'].replace('Z','+00:00')).timestamp()-time.time())
  assert 295<remaining<=301,remaining
 try:
  sql(f'''INSERT INTO "User" (id,username,email,"passwordHash","gameUsername","provisioningId",role,status,"createdAt","updatedAt","emailVerificationRequired") VALUES ('{uid}','{name}','{name}@example.invalid','!no-fixture-login','{name}','{uuid.uuid4()}','PLAYER','ACTIVE',now(),now(),false)''')
  for sid,digest in zip(ids,hashes):sql(f'''INSERT INTO "Session" (id,"tokenHash","csrfToken","userId","createdAt","expiresAt") VALUES ('{sid}','{digest}','{csrf}','{uid}',now(),now()+interval '5 minutes')''')
  for locale in ('ru','en'):
   status,raw=request('/'+locale+'/account');assert status==200
   html=raw.decode();assert name in html and 'name="currentPassword"' in html and f'href="/{locale}/bugs"' in html
   assert all(f'href="/{locale}/{page}"' not in html for page in ('bank','clan','assault','city','services','ratings'))
  checks+=['both_locales_remove_six_links','password_and_bug_controls_preserved']
  assert request('/api/auth/presence',0,'POST',origin='https://example.invalid')[0]==403
  assert request('/api/auth/presence',0,'POST',valid_csrf=False)[0]==403
  heartbeat();heartbeat(1);checks+=['csrf_enforced','five_minute_server_deadline']
  start=time.monotonic();ticks=0
  while time.monotonic()-start<seconds:
   time.sleep(min(20,seconds-(time.monotonic()-start)))
   heartbeat();ticks+=1
   if ticks%3==0:print(json.dumps(dict(progress_seconds=round(time.monotonic()-start),open_tab_heartbeat=True)),flush=True)
  if seconds>=305:
   assert json.loads(request('/api/auth/session',1)[1])['user'] is None
   assert request('/api/auth/presence',1,'POST')[0] in (401,403)
   assert json.loads(request('/api/auth/session',0)[1])['user']['username']==name
   checks+=['closed_session_expires_after_real_five_minutes','expired_session_cannot_revive','another_open_tab_survives_past_five_minutes']
  # A revoked session cannot be recreated by a heartbeat already in flight.
  sql(f'''DELETE FROM "Session" WHERE id='{ids[0]}' AND "userId"='{uid}' ''')
  assert request('/api/auth/presence',0,'POST')[0] in (401,403)
  checks+=['revoked_session_stays_revoked']
 finally:
  sql(f'''DELETE FROM "Session" WHERE "userId"='{uid}'; DELETE FROM "User" WHERE id='{uid}' AND username='{name}';''')
  assert fingerprint()==before,'Existing website users changed'
 return dict(passed=True,checks=checks,elapsed_seconds=round(seconds),only_owned_fixture_removed=True,existing_users_preserved=True,website_users=int(sql('SELECT count(*) FROM "User"')))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--base',default='http://127.0.0.1:3000');p.add_argument('--seconds',type=int,default=310);a=p.parse_args()
 print(json.dumps(run(a.base,a.seconds)),flush=True)
