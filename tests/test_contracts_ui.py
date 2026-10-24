"""Typed windows, privacy, consent and native TLS compatibility on temporary data."""
from types import SimpleNamespace
import json
import secrets
import struct
import time
import unittest

from tests import test_contracts_service as fixture
from server.contracts_ui import execute,handle,snapshot
from server.tls import read_bridge_preface,ContractsControl


class ContractsUITests(unittest.TestCase):
    def setUp(self): fixture.ContractsServiceTests.setUp(self)
    def call(self,index,action,value=None,request_id=None):
        request=dict(action=action,request_id=request_id or secrets.token_hex(16))
        if value is not None: request['value']=value
        return execute(self.service,self.sessions[index],request)
    def test_private_snapshot_and_invitation_consent(self):
        self.call(0,'create');self.call(0,'invite','Bob')
        a=snapshot(self.service,self.sessions[0]);b=snapshot(self.service,self.sessions[1]);c=snapshot(self.service,self.sessions[2])
        self.assertIsNone(b['party']);self.assertEqual(b['invitations'][0]['leader'],'Alice')
        self.assertFalse(c['invitations']);self.assertEqual(a['party']['members'][0]['name'],'Alice')
        self.assertNotIn('alice',json.dumps(a))
        invitation=b['invitations'][0]['id']
        self.call(1,'accept',invitation);state=self.call(0,'take','camp')
        self.assertEqual(len(state['party']['members']),2);self.assertFalse(state['permissions']['depart'])
        self.assertEqual(state['catalog'][0]['enemies'],5)
        self.call(0,'ready');state=self.call(1,'ready');self.assertFalse(state['permissions']['depart'])
        state=snapshot(self.service,self.sessions[0]);self.assertTrue(state['permissions']['depart'])
        with self.assertRaises(ValueError):self.call(1,'depart')
        state=self.call(0,'depart');self.assertEqual(state['party']['state'],'travelling')
        self.assertFalse(state['permissions']['start'])
    def test_retry_receipt_and_conflicting_retry(self):
        identity=secrets.token_hex(16)
        first=self.call(0,'create',request_id=identity);second=self.call(0,'create',request_id=identity)
        self.assertEqual(first['party']['id'],second['party']['id'])
        with self.assertRaises(ValueError):self.call(0,'disband',request_id=identity)
    def test_no_ownership_injection_or_unknown_action(self):
        for request in ({'action':'state','owner':'bob'},{'action':'state','request_id':'x'},
                        {'action':'sql','request_id':secrets.token_hex(16)},
                        {'action':'invite','value':'Bob\n!party disband','request_id':secrets.token_hex(16)}):
            with self.assertRaises(ValueError):execute(self.service,self.sessions[0],request)
        self.assertIsNone(self.service.member(self.sessions[0]))
    def test_wrong_token_disconnected_session_and_throttle(self):
        router=SimpleNamespace(contracts=self.service);session=self.sessions[0]
        session.contracts_ui_token=secrets.token_bytes(32)
        self.assertEqual(handle(router,b'x'*32,{'action':'state'})['code'],'not_authenticated')
        reply=handle(router,session.contracts_ui_token,{'action':'state'});self.assertTrue(reply['ok'])
        self.assertEqual(handle(router,session.contracts_ui_token,{'action':'state'})['code'],'rate_limited')
        session.stopping.set()
        self.assertEqual(handle(router,session.contracts_ui_token,{'action':'state'})['code'],'not_authenticated')
    def test_frozen_roster_and_foreign_fighter_rejected(self):
        self.call(0,'create')
        with self.assertRaises(ValueError):self.call(0,'select',[999999])
        self.call(0,'invite','Bob');self.call(1,'accept',snapshot(self.service,self.sessions[1])['invitations'][0]['id'])
        self.call(0,'take','camp')
        with self.assertRaises(ValueError):self.call(0,'select',[1])
        with self.assertRaises(ValueError):self.call(1,'cancel')
        self.assertIsNotNone(snapshot(self.service,self.sessions[0])['contract'])


class Fragments:
    def __init__(self,raw):self.raw=raw
    def settimeout(self,value):pass
    def recv(self,count):
        result=self.raw[:min(count,3)];self.raw=self.raw[len(result):];return result


class ContractsTLSHeaderTests(unittest.TestCase):
    def read(self,raw):return read_bridge_preface(Fragments(raw),time.monotonic()+1)
    def test_v3_fragmented_binding_and_legacy(self):
        token=secrets.token_bytes(32)
        result=self.read(struct.pack('!4sBBH',b'TIOT',3,1,31002)+bytes(38)+token)
        self.assertEqual(int(result),31002);self.assertEqual(result.language,'english');self.assertEqual(result.control_token,token)
        for version in (1,2):
            result=self.read(struct.pack('!4sBBH',b'TIOT',version,0,31002)+(bytes(38) if version==2 else b''))
            self.assertIsNone(result.control_token)
    def test_control_header_bounds_duplicate_and_truncation(self):
        token=secrets.token_bytes(32);raw=b'{"action":"state"}'
        header=lambda n:struct.pack('!4sBBH',b'TIOC',1,0,n)+bytes(38)+token
        result=self.read(header(len(raw))+raw);self.assertIsInstance(result,ContractsControl)
        self.assertEqual(result.token,token);self.assertEqual(result.request,{'action':'state'})
        for body in (b'{"action":"state","action":"create"}',b'[]',b'{"action":NaN}'):
            with self.assertRaises(ValueError):self.read(header(len(body))+body)
        with self.assertRaises(ValueError):self.read(header(4097))
        with self.assertRaises(EOFError):self.read(header(len(raw))+raw[:-1])


class ContractsTLSLiveTests(unittest.TestCase):
    def test_two_authenticated_tls_accounts_share_only_their_party(self):
        from dataclasses import replace
        import test_game_tls as tls_fixture
        import tempfile
        from unittest.mock import patch
        from tls_test_certificates import create
        certificates = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.object(tls_fixture, 'FIXTURES', create(certificates)))
        tls=tls_fixture.GameTLSTests();tls.setUp();self.addCleanup(tls.doCleanups)
        tls.case.config=replace(tls.case.config,contracts_enabled=True)
        tls.case.start();original=tls.connect;binding=[secrets.token_bytes(32)]
        def connect(kind,*,preface=None,**kwargs):
            if kind=='login' and preface is not None:
                preface=bytearray(preface);preface[4]=3;preface=bytes(preface)+bytes(38)+binding[0]
            return original(kind,preface=preface,**kwargs)
        tls.connect=connect
        first_token=binding[0]
        first=tls.handoff(tls.begin('alice',31001));tls.case.enter(first,'Alice')
        binding[0]=secrets.token_bytes(32);second_token=binding[0]
        second=tls.handoff(tls.begin('bob',31002));tls.case.enter(second,'Bob')
        def control(token,action,value=None):
            time.sleep(.18)
            request={'action':action}
            if action!='state':request['request_id']=secrets.token_hex(16)
            if value is not None:request['value']=value
            body=json.dumps(request).encode()
            channel=original('login')
            channel.sendall(struct.pack('!4sBBH',b'TIOC',1,0,len(body))+bytes(38)+token+body)
            def read(size):
                result=b''
                while len(result)<size:
                    part=channel.recv(size-len(result))
                    if not part:raise EOFError('Control channel ended')
                    result+=part
                return result
            reply=json.loads(read(int.from_bytes(read(4),'big')));channel.close();return reply
        self.assertEqual(control(b'x'*32,'state')['code'],'not_authenticated')
        self.assertTrue(control(first_token,'create')['ok'])
        self.assertTrue(control(first_token,'invite','Bob')['ok'])
        invited=control(second_token,'state')['state'];self.assertIsNone(invited['party'])
        self.assertEqual(len(invited['invitations']),1)
        self.assertTrue(control(second_token,'accept',invited['invitations'][0]['id'])['ok'])
        chosen=control(first_token,'take','camp');self.assertTrue(chosen['ok'],chosen)
        self.assertEqual(chosen['state']['contract']['name'],'Лагерь мародёров')
        denied=control(second_token,'cancel');self.assertFalse(denied['ok'])
        self.assertTrue(control(first_token,'cancel')['ok'])
        self.assertTrue(control(first_token,'disband')['ok'])
        tls.case.ping(first);tls.case.ping(second)
        first.sock.close()
        tls.until(lambda:'alice' not in tls.case.server.multi.active_accounts)
        self.assertEqual(control(first_token,'state')['code'],'not_authenticated')


if __name__=='__main__':unittest.main()
