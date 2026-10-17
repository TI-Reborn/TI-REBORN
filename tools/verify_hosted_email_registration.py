"""Verify hosted email gating with one owned QA account and a simulated mailbox.

Tests the live HTTP service and game bridge. The confirmation token is injected
only into this newly created QA profile: this does not prove real inbox delivery
or graphical game-client behavior. Existing accounts and saves are never edited.
"""
import argparse
import hashlib
import http.cookiejar
import json
from pathlib import Path
import re
import secrets
import subprocess
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
ORIGIN='https://ti-reborn.com'


class Browser:
    def __init__(self):
        self.opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(self,path,body=None,csrf=None):
        headers={'User-Agent':'Mozilla/5.0 TIREBORN-hosted-email-QA','Accept':'application/json'}
        data=None
        if body is not None:
            data=json.dumps(body).encode();headers.update({'Origin':ORIGIN,'Content-Type':'application/json','X-CSRF-Token':csrf})
        request=urllib.request.Request(ORIGIN+path,data=data,headers=headers)
        try:response=self.opener.open(request,timeout=25)
        except urllib.error.HTTPError as error:response=error
        with response:
            content=response.read(524288)
            return response.status,response.url,json.loads(content) if response.headers.get('Content-Type','').startswith('application/json') else None

    def session(self):
        status,_,body=self.request('/api/auth/session')
        assert status==200
        return body

    def mutate(self,path,body):
        return self.request(path,body,self.session()['csrfToken'])


def inspect_fixture(user_id,username,token_hash=None):
    assert re.fullmatch(r'[a-f0-9-]{36}',user_id) and re.fullmatch(r'qa_mail_[a-f0-9]{12}',username)
    sql='SELECT json_build_object(\'status\',status,\'required\',"emailVerificationRequired",\'verified\',"emailVerifiedAt" IS NOT NULL) FROM "User" WHERE id='+"'"+user_id+"'"
    if token_hash:
        assert re.fullmatch(r'[a-f0-9]{64}',token_hash)
        sql=('BEGIN; DO $$ BEGIN PERFORM id FROM "User" WHERE id='+"'"+user_id+"'"+
             ' AND username='+"'"+username+"'"+' AND status=\'PENDING\' AND "emailVerificationRequired"=true AND "emailVerifiedAt" IS NULL FOR UPDATE; END $$; '
             'UPDATE "EmailVerification" SET "tokenHash"='+"'"+token_hash+"'"+' WHERE "userId"='+"'"+user_id+"'"+'; COMMIT; '+sql)
    script="""
import json,sqlite3,subprocess
from contextlib import closing
r=subprocess.run(['runuser','-u','postgres','--','psql','-X','-qAt','-v','ON_ERROR_STOP=1','-d','tionline_web','-c',SQL],text=True,capture_output=True,check=True)
user=json.loads(r.stdout.strip())
with closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)) as db:
 exists=db.execute('SELECT EXISTS(SELECT 1 FROM accounts WHERE login=?)',(USERNAME,)).fetchone()[0]
print(json.dumps({'user':user,'game_account_exists':bool(exists)}))
""".replace('SQL',repr(sql)).replace('USERNAME',repr(username))
    result=subprocess.run(['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes',
                           '-o','ConnectTimeout=15','root@185.184.42.88','python3 -'],input=script,text=True,capture_output=True)
    if result.returncode:raise RuntimeError('Owned fixture inspection failed')
    return json.loads(result.stdout)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    if args.report.exists():parser.error('Preserve existing hosted report')
    username='qa_mail_'+secrets.token_hex(6)
    password=secrets.token_urlsafe(18)+'A7!'
    email='delivered+'+username+'@resend.dev'
    fixture_path=ROOT/'.secrets'/('hosted-email-'+username+'.json')
    fixture_path.write_text(json.dumps({'username':username,'password':password,'email':email})+'\n',encoding='utf-8')
    report={'kind':'hosted HTTP with owned fixture and provider simulated mailbox','fixture_username':username,
            'confirmation_token_is_test_fixture':True,'real_mailbox_delivery_verified':False,
            'graphical_game_client_validated':False,'checks':[],'passed':False}
    browser=Browser()
    try:
        status,_,payload=browser.mutate('/api/auth/register',{'username':username,'email':email,'password':password,'confirmPassword':password,'locale':'ru'})
        assert status==201 and payload['user']['status']=='PENDING' and payload['verificationRequired'] is True
        user_id=payload['user']['id']
        before=inspect_fixture(user_id,username)
        assert before['user']=={'status':'PENDING','required':True,'verified':False} and not before['game_account_exists']
        report['checks'].append('registration accepted by real mail provider; PENDING; no game account')
        assert browser.mutate('/api/auth/password',{'currentPassword':password,'newPassword':'ChangedPassword2026!','confirmPassword':'ChangedPassword2026!'})[0]==403
        assert browser.request('/api/services/status?slot=1')[0]==403
        assert browser.mutate('/api/auth/resend-verification',{'locale':'ru'})[0]==429
        assert urllib.parse.urlsplit(browser.request('/ru/bank')[1]).path=='/ru/verify-email'
        report['checks'].append('pending gameplay/password/bank denied; resend cooldown enforced')
        token=secrets.token_urlsafe(32)
        inspect_fixture(user_id,username,hashlib.sha256(token.encode()).hexdigest())
        assert browser.request('/ru/verify-email')[0]==200
        assert not inspect_fixture(user_id,username)['game_account_exists']
        assert browser.mutate('/api/auth/verify-email',{'token':token,'password':'IncorrectPassword2026!'})[0]==401
        assert not inspect_fixture(user_id,username)['user']['verified']
        report['checks'].append('opening page and wrong password do not confirm proof or create game account')
        assert browser.mutate('/api/auth/verify-email',{'token':token,'password':password})[0]==200
        after=inspect_fixture(user_id,username)
        assert after['user']=={'status':'ACTIVE','required':True,'verified':True} and after['game_account_exists']
        assert browser.mutate('/api/auth/verify-email',{'token':token,'password':password})[0]==400
        report['checks'].append('correct proof activates website and hosted game account; replay rejected')
        assert browser.mutate('/api/auth/logout',{})[0]==200
        assert browser.mutate('/api/auth/login',{'username':username,'password':password})[0]==200
        assert browser.session()['user']['status']=='ACTIVE'
        assert browser.mutate('/api/auth/logout',{})[0]==200
        report['checks'].append('hosted authoritative game credentials support login/logout')
        report['passed']=True
    except Exception as error:
        report['failure_type']=type(error).__name__
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
