"""Services V2 exercises the live city gate, routes, rollback and private tick."""
import json,threading,unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import test_city_operations as city_fixture
from server.city_services import CityServices,validate
from server.city_operations import CityError
from server.city_http import CityHTTP
from server import services_runtime
from tio.db_transaction import transaction
from tio.owned_pets import OwnedPetStore
from tio.protocol.pet_info import decode_pet_info

class CityServicesIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.case=city_fixture.CityOperationsTests(methodName='runTest');self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.manager=CityServices(self.case.router,operations=self.case.ops);self.case.router._city_services=self.manager
    def request(self,action,**extra):
        return dict(username='alice',slot=1,action=action,requestId='services-request-test-0001',**extra)
    def test_owned_dto_capacity_and_no_internal_owner(self):
        status=self.manager.status(dict(username='alice',slot=1))
        self.assertEqual(status['version'],2);self.assertTrue(status['canOperate'])
        self.assertEqual(status['personalWarehouse']['capacity'],32)
        self.assertEqual(status['clanWarehouse']['clan']['name'],'Alpha')
        self.assertFalse(status['services']['avatarsEnabled'])
        self.assertFalse(any(key in status for key in ('account','owner','path','receipt')))
        other=self.manager.status(dict(username='bob',slot=1));self.assertNotEqual(other['character'],status['character'])
    def test_nullable_uncreated_slot(self):
        status=self.manager.status(dict(username='alice',slot=5))
        self.assertIsNone(status['services']);self.assertIsNone(status['personalWarehouse']);self.assertFalse(status['canOperate'])
        with self.assertRaises(CityError):self.manager.action(dict(self.request('service_dismiss',petId=2),slot=5))
    def test_rename_receipt_replays_and_projection_rolls_back(self):
        payload=self.request('service_rename',petId=1,newName='NewAlice')
        accepted=self.manager.action(payload);again=self.manager.action(payload)
        self.assertFalse(accepted['replayed']);self.assertTrue(again['replayed'])
        self.assertEqual(accepted['receipt'],again['receipt']);self.assertEqual(again['receipt']['creditsDelta'],-3000)
        self.assertEqual(again['receipt']['goldDelta'],0)
        self.assertEqual(set(accepted['receipt']),{'requestId','action','creditsDelta','goldDelta'})
        before=self.case.rows()
        with patch.object(self.manager,'_status',side_effect=RuntimeError('projection')):
            with self.assertRaises(RuntimeError):self.manager.action(dict(payload,requestId='services-request-test-0002',newName='LaterAlice'))
        self.assertEqual(before,self.case.rows())
    def test_warehouse_payment_personal_and_shared_replay(self):
        with transaction(self.case.path) as db:db.execute("UPDATE wallets SET credits=50000 WHERE account='alice'")
        payload=self.request('warehouse_purchase',service=3,wanted=1,expectedClan=1)
        accepted=self.manager.action(payload);again=self.manager.action(payload)
        self.assertEqual(accepted['receipt']['creditsDelta'],-15000);self.assertTrue(again['replayed'])
        self.assertEqual(again['status']['balances']['credits'],35000)
        self.assertEqual(again['status']['clanWarehouse']['services'][0]['capacity'],40)
        other=self.manager.status(dict(username='bob',slot=1));self.assertEqual(other['clanWarehouse']['services'][0]['capacity'],40)
        self.assertEqual(other['balances']['credits'],10000)
        before=self.case.rows()
        with self.assertRaises(CityError):self.manager.action(self.request('service_rename',petId=1,newName='NewAlice'))
        self.assertEqual(before,self.case.rows())
    def test_avatar_disabled_and_main_dismiss_rejected_without_charge(self):
        before=self.case.rows()
        for payload in (self.request('service_avatar',petId=1,avatarId=123),self.request('service_dismiss',petId=1)):
            with self.assertRaises(CityError):self.manager.action(payload)
        self.assertEqual(before,self.case.rows())
    def test_strict_fields_and_opaque_foreign_owner(self):
        for payload in ({'username':'alice','slot':1,'action':[]},dict(self.request('service_dismiss',petId=1),owner='bob'),self.request('warehouse_purchase',service=True,wanted=1,expectedClan=1),dict(self.request('service_dismiss',petId=1),requestId='_'+'x'*20)):
            with self.assertRaises(CityError):validate(payload,action=True)
    def test_retained_and_online_unselected_fence(self):
        payload=self.request('service_rename',petId=1,newName='NewAlice')
        with patch.object(self.case.router.team_arena,'retained',return_value=True):
            self.case.router.team_arena.account_owners['alice']=1
            with self.assertRaises(CityError):self.manager.action(payload)
        self.case.router.team_arena.account_owners.clear()
        self.case.router.active_accounts['fixture']=SimpleNamespace(account='alice',probe_character_id=None)
        with self.assertRaises(CityError):self.manager.action(payload)
    def test_http_owner_bound_success_and_invalid_requests(self):
        server=CityHTTP(self.case.router,city_fixture.KEY,port=0,operations=self.case.ops).start();self.addCleanup(server.close)
        endpoint='http://127.0.0.1:'+str(server.http.server_port)+'/v2/services/status'
        body=json.dumps(dict(username='alice',slot=1)).encode()
        req=Request(endpoint,data=body,headers={'Content-Type':'application/json','Authorization':'Bearer '+city_fixture.KEY})
        with urlopen(req,timeout=5) as response:result=json.loads(response.read())
        self.assertEqual(result['version'],2);self.assertEqual(result['username'],'alice')
        with self.assertRaises(HTTPError) as ctx:urlopen(Request(endpoint,data=body,headers={'Content-Type':'application/json'}),timeout=5)
        self.assertEqual(ctx.exception.code,401)

if __name__=='__main__':unittest.main()
