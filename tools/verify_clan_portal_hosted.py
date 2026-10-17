"""Owned-session HTTPS reads and guaranteed-invalid crest/webhook requests.

No account/character creation, valid BMP, order/checkout, paid provider call or
gameplay mutation. Secrets/full payloads never enter the sanitized report.
"""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import re
import secrets
import struct
import urllib.error
import urllib.parse
import urllib.request

from tools.verify_portal_hosted import Client,Document,Response,Verifier,VISIBLE_KEY,CYRILLIC,credentials_path

ROOT=Path(__file__).resolve().parents[1]


class RawClient(Client):
    def raw(self,path,body=b'BM',*,token=None,origin=None,content_type='image/bmp'):
        headers={'User-Agent':'Tionline-Portal-QA/1.0','Accept':'application/json','Content-Type':content_type}
        if token is not None:headers['X-CSRF-Token']=token
        if origin is not None:headers['Origin']=origin
        request=urllib.request.Request(self.base_url+path,data=body,headers=headers,method='POST')
        try:response=self.opener.open(request,timeout=30)
        except urllib.error.HTTPError as error:response=error
        with response:return Response(response.status,response.geturl(),response.headers,response.read(1024*1024))


def denied(verifier,response,status,error):
    verifier.require(response.status==status,'guard_http_status',expected=status,actual=response.status)
    verifier.require(response.json().get('error')==error,'guard_error_code')
    verifier.require(response.headers.get('Cache-Control')=='no-store','guard_no_store')
    return dict(httpStatus=status,errorCode=error)


def status(verifier,client,username,slot):
    response=client.request('/api/clan/status?slot='+str(slot))
    verifier.require(response.status==200,'clan_status_http',expected=200,actual=response.status)
    body=response.json()
    verifier.require(body.get('username')==username and body.get('slot')==slot,'owned_slot_binding')
    characters=body.get('characters');verifier.require(isinstance(characters,list) and len(characters)<=5,'character_schema')
    verifier.require(all(type(c.get('slot')) is int and 1<=c['slot']<=5 and isinstance(c.get('name'),str) for c in characters),'owned_character_schema')
    verifier.require(len({c['slot'] for c in characters})==len(characters),'duplicate_owned_slot')
    selected=next((c['name'] for c in characters if c['slot']==slot),None)
    verifier.require(body.get('character')==selected,'selected_owned_name')
    verifier.require(type(body.get('canUpload')) is bool and body.get('cost')==1000,'crest_authority_schema')
    verifier.require(body.get('credits') is None or type(body['credits']) is int and 0<=body['credits']<=0xffffffff,'credit_schema')
    for field in ('clan','alliance'):
        row=body.get(field)
        verifier.require(row is None or isinstance(row,dict) and type(row.get('id')) is int and 1<=row['id']<=0xffffffff
            and isinstance(row.get('name'),str) and type(row.get('crestId')) is int and 0<=row['crestId']<=0xffffffff,'crest_status_schema')
    verifier.require(response.headers.get('Cache-Control')=='no-store','status_no_store')
    return body


def page(verifier,client,locale,*,anonymous=False):
    response=client.request('/'+locale+'/clan');doc=Document(response.body.decode('utf-8'))
    expected='/'+locale+('/login' if anonymous else '/clan')
    verifier.require(response.status==200 and urllib.parse.urlsplit(response.url).path==expected,'clan_page_route')
    verifier.require(doc.lang==locale and bool(doc.title.strip()) and not VISIBLE_KEY.search(doc.visible),'localized_clan_page')
    if locale=='ru':verifier.require(bool(CYRILLIC.search(doc.visible)),'cyrillic_clan_page')
    if not anonymous:verifier.require('id="clan-crest-file"' in response.body.decode('utf-8') and '1000' in doc.visible,'crest_controls_and_tariff')
    return dict(locale=locale,httpStatus=200,redirectToLogin=anonymous,localized=True)


def owned_checks(verifier,fixture,index):
    client=RawClient(verifier.base_url);username=fixture['username'];prefix='owned_fixture_'+str(index)
    def login():
        response=client.mutate('/api/auth/login',dict(username=username,password=fixture['password']))
        verifier.require(response.status==200,'owned_login',expected=200,actual=response.status)
        verifier.require(client.session().get('user',{}).get('gameUsername')==username,'active_linked_account')
        return dict(httpStatus=200,activeGameLink=True)
    verifier.check(prefix+'_login',login)
    try:
        verifier.check(prefix+'_clan_ru',lambda:page(verifier,client,'ru'))
        verifier.check(prefix+'_clan_en',lambda:page(verifier,client,'en'))
        before={}
        for slot in range(1,6):
            def read(slot=slot):
                value=status(verifier,client,username,slot);before[slot]=value
                return dict(slot=slot,httpStatus=200,ownedSlotBinding=True,characterPresent=value['character'] is not None,
                    ownedCharacterCount=len(value['characters']),clanPresent=value['clan'] is not None,alliancePresent=value.get('alliance') is not None,
                    canUpload=value['canUpload'],cost=1000)
            verifier.check(prefix+'_clan_status_slot_'+str(slot),read)
        def bank():
            response=client.request('/api/bank/status?slot=1');verifier.require(response.status==200,'bank_status_http',expected=200,actual=response.status)
            data=response.json();verifier.require(data.get('username')==username and data.get('slot')==1,'bank_owned_slot')
            verifier.require(data.get('configured') is False and data.get('canPurchase') is False and data.get('reason')=='not_configured','provider_must_remain_disabled')
            verifier.require((data.get('currency'),data.get('minorUnitsPerGold'),data.get('minimumGold'))==('eur',1,50),'bank_public_tariff')
            verifier.require(data.get('character')==before[1]['character'] and data.get('characters')==before[1]['characters'],'bank_clan_character_binding')
            verifier.require(response.headers.get('Cache-Control')=='no-store','bank_no_store')
            return dict(httpStatus=200,ownedSlotBinding=True,currency='eur',minorUnitsPerGold=1,minimumGold=50,configured=False,canPurchase=False,reason='not_configured')
        verifier.check(prefix+'_bank_status_tariff',bank)
        for query in ('slot=0','slot=6','slot=1&slot=2','slot=1&username=foreign','slot=1&account=foreign','slot=1&owner=foreign'):
            verifier.check(prefix+'_clan_query_guard_'+query.split('&')[-1].split('=')[0]+'_'+query[5:6],
                lambda query=query:denied(verifier,client.request('/api/clan/status?'+query),400,'common.errors.invalid_request'))
        token=client.session()['csrfToken'];target='/api/clan/crest?slot=1&kind=clan&requestId=readonly_'+secrets.token_hex(12)
        verifier.check(prefix+'_foreign_origin',lambda:denied(verifier,client.raw(target,token=token,origin='https://invalid.example'),403,'auth.errors.csrf'))
        verifier.check(prefix+'_missing_csrf',lambda:denied(verifier,client.raw(target,origin=verifier.base_url),403,'auth.errors.csrf'))
        verifier.check(prefix+'_malformed_bmp',lambda:denied(verifier,client.raw(target,token=token,origin=verifier.base_url),400,'invalid_crest'))
        verifier.check(prefix+'_oversized_bmp',lambda:denied(verifier,client.raw(target,b'BM'+bytes(823),token=token,origin=verifier.base_url),413,'common.errors.invalid_request'))
        topdown=b'BM'+struct.pack('<III',822,0,54)+struct.pack('<IiiHHIIiiII',40,16,-16,1,24,0,768,0,0,0,0)+bytes(768)
        verifier.check(prefix+'_native_incompatible_topdown_bmp',lambda:denied(verifier,client.raw(target,topdown,token=token,origin=verifier.base_url),400,'invalid_crest'))
        verifier.check(prefix+'_wrong_media_type',lambda:denied(verifier,client.raw(target,b'{}',token=token,origin=verifier.base_url,content_type='application/json'),415,'common.errors.invalid_request'))
        def unchanged():
            verifier.require(all(status(verifier,client,username,slot)==value for slot,value in before.items()),'owned_status_changed')
            return dict(allOwnedSlotStatusesUnchanged=True,malformedUploadsAccepted=0,validBmpSent=False)
        verifier.check(prefix+'_status_unchanged_after_rejections',unchanged)
    finally:
        def logout():
            response=client.mutate('/api/auth/logout',{});verifier.require(response.status==200,'final_logout',expected=200,actual=response.status)
            verifier.require(client.session().get('user') is None,'session_after_logout')
            return dict(loggedOut=True)
        verifier.check(prefix+'_logout',logout)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--credentials-file',required=True)
    parser.add_argument('--report',required=True,type=Path)
    args=parser.parse_args();protected=credentials_path(args.credentials_file,existing=True)
    data=json.loads(protected.read_text(encoding='utf-8'));base=data.get('baseUrl')
    parsed=urllib.parse.urlsplit(base)
    if parsed.scheme!='https' or parsed.hostname!='ti-reborn.com' or parsed.path not in ('','/') or parsed.username or parsed.password or parsed.query or parsed.fragment:parser.error('Expected the owned trusted portal origin')
    fixtures=data.get('fixtures',[])
    if not 1<=len(fixtures)<=2 or any(not isinstance(f,dict) or not re.fullmatch(r'webqa_[a-z0-9_]{3,26}',f.get('username',''))
        or not re.fullmatch(r'[\x21-\x7e]{12,64}',f.get('password','')) for f in fixtures):parser.error('Expected saved owned QA fixtures')
    if args.report.exists():parser.error('Preserve prior evidence')
    verifier=Verifier(base.rstrip('/'),args.report.resolve());anonymous=RawClient(verifier.base_url)
    verifier.report.update(kind='bounded trusted HTTPS owned clan/status and invalid security requests',createdFixtures=0,
        existingFixturesUsed=len(fixtures),validCrestUploads=0,orderCheckoutRequests=0,paidProviderCalls=0,gameDataMutationAuthorized=False)
    for locale in ('ru','en'):verifier.check('anonymous_clan_'+locale,lambda locale=locale:page(verifier,anonymous,locale,anonymous=True))
    for name in ('clan','bank'):verifier.check('unauthenticated_'+name+'_status',lambda name=name:denied(verifier,anonymous.request('/api/'+name+'/status?slot=1'),401,'auth.errors.unauthorized'))
    verifier.check('unsigned_stripe_webhook',lambda:denied(verifier,anonymous.raw('/api/bank/stripe/webhook',b'{}',content_type='application/json'),400,'common.errors.invalid_request'))
    try:
        for index,fixture in enumerate(fixtures,1):owned_checks(verifier,fixture,index)
    finally:
        verifier.report['finishedAt']=datetime.now(timezone.utc).isoformat()
        verifier.report['limits']=['No valid crest installation/removal or payment/checkout was sent.',
            'Owned saved-slot statuses may legitimately be empty; clan rights for populated characters were tested separately by the root game QA.',
            'No browser JavaScript, mobile layout, live image rendering or graphical game-client validation.']
        verifier.save_report()
    print(json.dumps(dict(passed=verifier.report['passed'],passedChecks=sum(c['passed'] for c in verifier.report['checks']),
        totalChecks=len(verifier.report['checks']),createdFixtures=0,validCrestUploads=0,paidProviderCalls=0,report=str(verifier.report_path))))
    return 0 if verifier.report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
