"""Read-only public rankings use real independent accounts, private hops and locks."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timezone
from email.message import Message
import json
import sqlite3
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import test_multi_account as fixture
from server.city_operations import CityError
from server.city_http import CityHTTP
from server.ratings_public import RatingsPublic, validate_payload, validate_response
from tio import team_ratings, rating_completion
from wallet_fixture import fund_wallet

NOW = int(datetime(2026, 10, 8, tzinfo=timezone.utc).timestamp())
NOVEMBER = int(datetime(2026, 11, 1, tzinfo=timezone.utc).timestamp())
KEY = 'ratings-fixture-key-000000000000000000'


class RatingsPublicTests(unittest.TestCase):
    def setUp(self):
        self.case=fixture.MultiAccountTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.path=self.case.config.database;self.now=NOW
        self.router=SimpleNamespace(config=self.case.config,team_arena=SimpleNamespace(lock=threading.RLock()),
                                    server=SimpleNamespace(stopping=threading.Event()))
        self.public=RatingsPublic(self.router,clock=lambda:self.now)

    def request(self,format='pairs',scope=None,offset=0,**changes):
        return dict(username='alice',format=format,scope=scope,offset=offset,limit=10,**changes)

    def rows(self):
        with closing(sqlite3.connect(self.path)) as db:
            return {table:tuple(db.execute('SELECT * FROM "'+table+'"').fetchall())
                    for table, in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    def accounts(self):
        names=('alice','bob','carol','dave','eve','fred','gina','hank')
        for name in names[2:]:
            self.case.accounts.create(name,fixture.PASSWORD,character=name.capitalize())
            fund_wallet(self.path,name,credits=3000,gold=7)
        return names

    def match(self,format,teams,identity,now=None):
        backend=team_ratings if format=='pairs' else rating_completion
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE')
            frozen=backend.admit(db,identity,teams,now=self.now if now is None else now)
            backend.settle(db,identity,backend.report(frozen,0,(0,1)),now=self.now if now is None else now)
        return frozen

    def test_empty_status_is_readonly_without_wallet_or_character_requirement(self):
        before=self.rows()
        for format in ('pairs','wall'):
            result=self.public.status(self.request(format));self.assertEqual(result['ratings']['rows'],[])
            self.assertEqual(result['ratings']['scope'],'2026-10');self.assertEqual(result['ratings']['seasonState'],'not_created')
        self.assertEqual(before,self.rows())
        self.case.accounts.create('newplayer',fixture.PASSWORD)
        before=self.rows();self.assertEqual(self.public.status({**self.request(),'username':'newplayer'})['ratings']['total'],0)
        self.assertEqual(before,self.rows());self.assertNotIn('newplayer',repr(before.get('wallets')))

    def test_pairs_and_wall_are_separate_safe_and_preserve_all_saved_rows(self):
        names=self.accounts();self.match('pairs',(names[:2],names[2:4]),'pair')
        self.match('wall',(names[:4],names[4:]),'wall');before=self.rows()
        for format,size in (('pairs',2),('wall',4)):
            dto=self.public.status(self.request(format,'all'))['ratings'];self.assertEqual(dto['total'],2)
            self.assertTrue(all(len(row['names'])==size for row in dto['rows']))
            self.assertEqual(dto['rewards'],[]);self.assertFalse(dto['historicalSeasonRewardsConfirmed'])
            self.assertTrue(all('members' not in row and 'mu' not in row for row in dto['rows']))
            self.assertNotIn('carol',json.dumps(dto));self.assertIn('Carol',json.dumps(dto))
        self.assertEqual(before,self.rows())

    def test_actual_pair_pagination_and_deleted_character_names_do_not_leak_login(self):
        names=self.accounts();seen=set()
        for index in range(1,8):
            first=(names[0],names[index]);remaining=[name for name in names if name not in first]
            second=next((remaining[a],remaining[b]) for a in range(5) for b in range(a+1,6)
                        if tuple(sorted((remaining[a],remaining[b]))) not in seen)
            seen.add(tuple(sorted(second)))
            self.match('pairs',(first,second),'page'+str(index),now=NOW+index*86401)
        with closing(sqlite3.connect(self.path)) as db,db:db.execute("DELETE FROM characters WHERE account='carol'")
        self.now=NOW+7*86401;before=self.rows()
        first=self.public.status(self.request('pairs','all'))['ratings'];second=self.public.status(self.request('pairs','all',10))['ratings']
        self.assertGreater(first['total'],10);self.assertEqual(len(first['rows']),10);self.assertTrue(first['hasMore'])
        self.assertEqual(first['total'],len(first['rows'])+len(second['rows']));self.assertFalse(second['hasMore'])
        self.assertFalse(set(row['teamId'] for row in first['rows'])&set(row['teamId'] for row in second['rows']))
        self.assertIn('Удалённый персонаж',repr(first['rows']+second['rows']));self.assertNotIn("'carol'",repr(first['rows']+second['rows']))
        self.assertEqual(before,self.rows())

    def test_month_boundary_read_does_not_create_or_close_seasons_then_archive_reads(self):
        names=self.accounts();self.match('wall',(names[:4],names[4:]),'october');self.now=NOVEMBER
        before=self.rows();self.assertEqual(self.public.status(self.request('wall'))['ratings']['seasonState'],'not_created')
        old=self.public.status(self.request('wall','2026-10'))['ratings'];self.assertEqual(old['seasonState'],'open')
        self.assertEqual(before,self.rows())
        with closing(sqlite3.connect(self.path)) as db,db:rating_completion.current(db,self.now)
        before=self.rows();old=self.public.status(self.request('wall','2026-10'))['ratings']
        self.assertEqual(old['seasonState'],'archived');self.assertTrue(old['archived']);self.assertEqual(old['total'],2)
        self.assertEqual(before,self.rows())

    def test_query_only_connection_prohibits_accidental_writer_and_missing_database(self):
        before=self.rows()
        def writer(db,**_):db.execute("UPDATE wallets SET gold=gold+100 WHERE account='alice'")
        with patch('tio.rating_completion.public_listing',side_effect=writer):
            with self.assertRaises(sqlite3.OperationalError):self.public.status(self.request())
        self.assertEqual(before,self.rows())
        self.public.path=self.path.parent/'never-created.db'
        with self.assertRaises(sqlite3.OperationalError):self.public.status(self.request())
        self.assertFalse(self.public.path.exists())

    def test_schema_rejects_identity_controls_bools_unbounded_queries_and_unknown_account(self):
        before=self.rows();valid=self.request()
        for changes in ({'username':'ALICE'},{'username':'alice;SELECT'},{'format':'3v3'},{'scope':'2026-13'},
                        {'scope':'0000-01'},{'scope':'9999-01'},{'scope':'٢٠٢٦-01'},{'offset':True},{'offset':10.0},
                        {'offset':1},{'offset':10000},{'limit':100},{'limit':True},{'owner':'bob'},{'slot':1}):
            with self.subTest(changes=changes),self.assertRaises(CityError):self.public.status({**valid,**changes})
        with self.assertRaises(CityError) as error:self.public.status({**valid,'username':'unknown'})
        self.assertEqual(error.exception.status,404);self.assertEqual(before,self.rows())

    def test_status_reads_while_arena_lock_is_held(self):
        with ThreadPoolExecutor(max_workers=1) as pool:
            with self.router.team_arena.lock:
                future = pool.submit(self.public.status, self.request())
                self.assertEqual(future.result(timeout=2)['ratings']['total'], 0)

    def test_status_rechecks_stop_during_listing(self):
        original = rating_completion.public_listing

        def listing(db, **kwargs):
            self.router.server.stopping.set()
            return original(db, **kwargs)

        with patch.object(rating_completion, 'public_listing', side_effect=listing):
            with self.assertRaises(CityError) as error:
                self.public.status(self.request())
        self.assertEqual(error.exception.status, 503)

    def test_response_validator_rejects_foreign_query_extra_secret_and_inconsistent_rows(self):
        names=self.accounts();self.match('wall',(names[:4],names[4:]),'wall');request=self.request('wall');sample=self.public.status(request)
        def mutate(path,value):
            changed=deepcopy(sample);cursor=changed
            for key in path[:-1]:cursor=cursor[key]
            cursor[path[-1]]=value;return changed
        for bad in (mutate(('username',),'bob'),mutate(('ratings','format'),'pairs'),mutate(('ratings','scope'),'all'),
                    mutate(('ratings','total'),3),mutate(('ratings','offset'),10),mutate(('ratings','hasMore'),True),
                    mutate(('ratings','rows',0,'names'),['Alice']),mutate(('ratings','rows',0,'skill'),401),
                    mutate(('ratings','rewards'),[{'gold':1}]),{**sample,'owner':'secret'}):
            with self.assertRaises(ValueError):validate_response(bad,request)


class RatingsHTTPTests(unittest.TestCase):
    setUp=RatingsPublicTests.setUp
    request=RatingsPublicTests.request
    rows=RatingsPublicTests.rows
    def call(self,service,payload,key=KEY,raw=None):
        request=Request('http://127.0.0.1:'+str(service.http.server_port)+'/v1/ratings/status',
            data=json.dumps(payload).encode() if raw is None else raw,
            headers={'Content-Type':'application/json','Authorization':'Bearer '+key},method='POST')
        try:response=urlopen(request,timeout=3)
        except HTTPError as error:response=error
        with response:return response.status,json.loads(response.read())

    def test_loopback_http_uses_ratings_facade_and_never_city_mutations(self):
        city=Mock();service=CityHTTP(self.router,KEY,port=0,operations=city,ratings=self.public).start();self.addCleanup(service.close)
        before=self.rows();status,result=self.call(service,self.request());self.assertEqual(status,200);self.assertEqual(result,self.public.status(self.request()))
        self.assertEqual(self.call(service,self.request(),key='wrong')[0],401)
        self.assertEqual(self.call(service,self.request(),raw=b'{"username":"alice","username":"bob"}')[0],400)
        self.assertEqual(self.call(service,{**self.request(),'owner':'bob'})[0],400);city.status.assert_not_called();city.action.assert_not_called()
        self.assertEqual(before,self.rows())


class RatingsGatewayTests(unittest.TestCase):
    setUp=RatingsPublicTests.setUp
    request=RatingsPublicTests.request
    rows=RatingsPublicTests.rows
    def gateway(self):
        from server.bank_gateway import create_app
        return create_app(self.path,KEY).test_client()

    def test_private_proxy_checks_auth_and_identity_before_any_forward(self):
        client=self.gateway();before=self.rows();headers={'Authorization':'Bearer '+KEY}
        with patch('urllib.request.urlopen') as transport:
            self.assertEqual(client.post('/v1/ratings/status',json=self.request()).status_code,401)
            for payload,status in (({**self.request(),'username':'unknown'},404),({**self.request(),'slot':1},400),
                                   ({**self.request(),'offset':True},400),({**self.request(),'scope':'2026-13'},400)):
                self.assertEqual(client.post('/v1/ratings/status',json=payload,headers=headers).status_code,status)
            self.assertEqual(client.post('/v1/ratings/status',data=b'{"username":"alice","username":"bob"}',headers={**headers,'Content-Type':'application/json'}).status_code,400)
            transport.assert_not_called()
        self.assertEqual(before,self.rows())

    def test_private_proxy_to_real_loopback_core_is_bounded_and_readonly(self):
        service=CityHTTP(self.router,KEY,port=0,ratings=self.public).start();self.addCleanup(service.close)
        client=self.gateway();before=self.rows();original=urlopen
        def transport(request,timeout):
            self.assertEqual(request.full_url,'http://127.0.0.1:8083/v1/ratings/status');self.assertEqual(timeout,3)
            forwarded=Request(request.full_url.replace(':8083/',':'+str(service.http.server_port)+'/'),data=request.data,headers=dict(request.headers),method='POST')
            return original(forwarded,timeout=timeout)
        with patch('urllib.request.urlopen',side_effect=transport):
            reply=client.post('/v1/ratings/status',json=self.request(),headers={'Authorization':'Bearer '+KEY})
        self.assertEqual(reply.status_code,200);self.assertEqual(reply.json,self.public.status(self.request()))
        self.assertEqual(reply.headers['Cache-Control'],'no-store');self.assertEqual(before,self.rows())

    def test_private_proxy_rejects_malformed_oversized_foreign_or_secret_errors(self):
        client=self.gateway();headers={'Authorization':'Bearer '+KEY};sample=self.public.status(self.request())
        class Reply:
            def __init__(self,raw,status=200,content_type='application/json'):
                self.raw,self.status=raw,status;self.headers=Message();self.headers['Content-Type']=content_type
            def __enter__(self):return self
            def __exit__(self,*_):pass
            def read(self,limit):return self.raw[:limit]
        for reply in (Reply(b'['),Reply(b'x'*65537),Reply(json.dumps({**sample,'username':'bob'}).encode()),
                      Reply(json.dumps(sample).encode(),content_type='text/html'),Reply(b'{"error":"private_sql"}',400),
                      Reply(b'{"error":"service_unavailable","path":"secret"}',503)):
            with patch('urllib.request.urlopen',return_value=reply):
                response=client.post('/v1/ratings/status',json=self.request(),headers=headers)
                self.assertEqual(response.status_code,503);self.assertEqual(response.json,dict(error='service_unavailable'))
        with patch('urllib.request.urlopen',side_effect=OSError('private details')):
            response=client.post('/v1/ratings/status',json=self.request(),headers=headers)
            self.assertEqual(response.status_code,503);self.assertNotIn('private details',repr(response.json))


if __name__=='__main__':unittest.main()
