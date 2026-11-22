"""Integration against the inspected hosted runtime; see check_game_operations.py."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen

import test_city_operations as fixture
from server.city_services import CityServices, validate
from server.city_operations import CityError
from server.city_http import CityHTTP
from server.services_v2 import ServicesV2
from server import services_runtime
from server.service_operations import (SERVICE_OPERATIONS, ServiceContext,
    execute_service, prepare_service)
from tio.db_transaction import transaction
from tio.services_completion import ServiceRejected
from tio.owned_pets import OwnedPetStore
from tio.protocol.pet_info import decode_pet_info,encode_pet_info,PetInfo
from tio.protocol.item_list import encode_item_list,decode_item_list
from tio.protocol.asset_count import decode_asset_count


class ServiceOperationTests(unittest.TestCase):
    def setUp(self):
        self.case=fixture.CityOperationsTests(methodName='runTest');self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.manager=CityServices(self.case.router,operations=self.case.ops)
        self.case.router._city_services=self.manager

    def request(self,kind='service_rename',username='alice',identity='operation-tests-0001',**args):
        return dict(username=username,slot=1,action=kind,requestId=identity,**args)

    def wallet(self,owner):
        return self.case.read('SELECT credits,gold FROM wallets WHERE account=?',(owner,))[0]

    def test_public_rename_replay_debits_once_and_keeps_other_account(self):
        before=self.wallet('alice');other=self.wallet('bob')
        request=self.request(petId=1,newName='AliceNew')
        accepted=self.manager.action(request);replayed=self.manager.action(request)
        self.assertEqual(accepted['receipt']['creditsDelta'],-3000)
        self.assertEqual(accepted['receipt']['goldDelta'],0)
        self.assertFalse(accepted['replayed']);self.assertTrue(replayed['replayed'])
        self.assertEqual(accepted['receipt'],replayed['receipt'])
        self.assertEqual(self.wallet('alice'),(before[0]-3000,before[1]))
        self.assertEqual(self.wallet('bob'),other)

    def test_native_and_portal_use_the_same_checked_registry(self):
        session=SimpleNamespace(router=self.case.router,database=self.case.path,account='bob')
        before=self.wallet('bob')
        with patch.object(SERVICE_OPERATIONS,'execute',wraps=SERVICE_OPERATIONS.execute) as execute:
            self.manager.action(self.request(petId=1,newName='AliceNew'))
            with patch.object(services_runtime,'refresh_inventory',return_value=()):
                packets=services_runtime.native(session,command='/changename Bob BobNew')
            self.assertEqual([call.args[0].name for call in execute.call_args_list],
                             ['service_rename','service_rename_command'])
        self.assertEqual(session.probe_character_name,b'BobNew')
        self.assertEqual(self.wallet('bob'),(before[0]-3000,before[1]))
        self.assertTrue(packets)

    def test_native_dismiss_schedules_owned_recruit_without_deleting_or_charging(self):
        raw=self.case.read("SELECT pet_packet FROM owned_pets WHERE account='alice' AND pet_id=1")[0][0]
        pet=decode_pet_info(bytes(raw),human_equipment=True)
        fields={**pet.fields,'0x8c43eb':777,'0x8c4489':b'Recruit'}
        OwnedPetStore(self.case.path).ensure('alice',encode_pet_info(PetInfo(True,fields)),encode_item_list(777,()),human=True)
        with transaction(self.case.path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS hired_candidates(account TEXT,candidate_id INTEGER,pet_id INTEGER,PRIMARY KEY(account,candidate_id))')
            db.execute("INSERT INTO hired_candidates VALUES ('alice',777,777)")
        before=self.wallet('alice')
        session=SimpleNamespace(router=self.case.router,database=self.case.path,account='alice')
        with patch.object(services_runtime,'refresh_inventory',return_value=()):
            result=services_runtime.native(session,pet_id=777)
        self.assertTrue(result)
        rows=self.case.read("SELECT completed_at FROM service_dismissals WHERE account='alice' AND pet_id=777")
        self.assertEqual(rows,[(None,)])
        self.assertTrue(self.case.read("SELECT 1 FROM owned_pets WHERE account='alice' AND pet_id=777"))
        self.assertEqual(self.wallet('alice'),before)

    def test_dogmeat_claim_replay_has_exactly_one_reward(self):
        with transaction(self.case.path) as db:
            db.execute("INSERT INTO service_dog_meat_rewards(account,pet_id) VALUES ('alice',777)")
        before=self.wallet('alice');other=self.wallet('bob')
        request=self.request('service_claim_dogmeat',dismissedPetId=777,petId=1)
        first=self.manager.action(request);again=self.manager.action(request)
        self.assertFalse(first['replayed']);self.assertTrue(again['replayed'])
        inv=OwnedPetStore(self.case.path).inventory('alice',1)
        self.assertEqual(sum(i.count for i in decode_item_list(inv)[1] if i.template_id==32),1)
        self.assertEqual(self.wallet('alice'),before);self.assertEqual(self.wallet('bob'),other)

    def test_native_unknown_old_name_does_not_charge(self):
        before=self.case.rows()
        session=SimpleNamespace(router=self.case.router,database=self.case.path,account='alice')
        with self.assertRaises(ServiceRejected):services_runtime.native(session,command='/changename Unknown NewName')
        self.assertEqual(before,self.case.rows())

    def test_native_rename_identifies_the_selected_recruit_by_id(self):
        store = OwnedPetStore(self.case.path)
        pet = decode_pet_info(store.list('alice')[0][1], human_equipment=True)
        for owner, pet_id in (('alice', 2), ('alice', 3), ('bob', 3)):
            fields = {**pet.fields, '0x8c43eb': pet_id, '0x8c4489': 'Иван Смирнов'.encode('cp1251')}
            store.ensure(owner, encode_pet_info(PetInfo(True, fields)), encode_item_list(pet_id, ()), human=True)
        session = SimpleNamespace(router=self.case.router, database=self.case.path, account='alice')
        before = self.wallet('alice')
        other = self.wallet('bob')

        request = b'\xb9\x06\x03\0\0\0NewName\0'
        packets = services_runtime.native(session, rename_packet=request)
        services_runtime.native(session, rename_packet=request)

        def names(owner):
            return {pet_id: decode_pet_info(raw, human_equipment=True).fields['0x8c4489'].decode('cp1251')
                    for pet_id, raw, _ in store.list(owner) if pet_id != 1}

        self.assertEqual(names('alice'), {2: 'Иван Смирнов', 3: 'NewName'})
        self.assertEqual(names('bob'), {3: 'Иван Смирнов'})
        self.assertEqual(self.wallet('alice'), (before[0] - 3000, before[1]))
        self.assertEqual(self.wallet('bob'), other)
        self.assertEqual(decode_asset_count(next(p for p in packets if p.startswith(b'\xc8\x39'))).credits,
                         before[0] - 3000)

    def test_facade_uses_same_registry_and_binds_authenticated_principal(self):
        facade=ServicesV2(self.case.path,self.case.router.team_arena.lock,
                          lambda db,principal,slot,owner:True,helper=self.manager.helper)
        payload=self.request(petId=1,newName='AliceNew')
        with patch.object(SERVICE_OPERATIONS,'execute',wraps=SERVICE_OPERATIONS.execute) as execute:
            result=facade.action('alice',payload)
            self.assertEqual(execute.call_count,1)
        self.assertEqual(result['receipt']['creditsDelta'],-3000)
        before=self.case.rows()
        with self.assertRaises(ServiceRejected):facade.action('bob',payload)
        self.assertEqual(before,self.case.rows())

    def test_unknown_foreign_pet_and_disabled_services_do_not_write(self):
        before=self.case.rows()
        for kind,args in [('service_rename',dict(petId=99999,newName='NameNew')),
                          ('service_avatar',dict(petId=1,avatarId=123)),
                          ('service_dismiss',dict(petId=1))]:
            with self.subTest(kind=kind),self.assertRaises(CityError):
                self.manager.action(self.request(kind,**args))
            self.assertEqual(before,self.case.rows())

    def test_projection_failure_rolls_back_charge_name_and_both_receipts(self):
        before=self.case.rows()
        with patch.object(self.manager,'_status',side_effect=RuntimeError('projection failure')):
            with self.assertRaises(RuntimeError):
                self.manager.action(self.request(petId=1,newName='AliceNew'))
        self.assertEqual(before,self.case.rows())

    def test_bad_result_rolls_back_execution_and_is_not_a_business_rejection(self):
        before=self.case.rows()
        with patch('server.service_operations._result',side_effect=RuntimeError('bad result')):
            with self.assertRaises(RuntimeError):
                self.manager.action(self.request(petId=1,newName='AliceNew'))
        self.assertEqual(before,self.case.rows())

    def test_same_request_id_is_scoped_to_owner_and_conflicting_reuse_rejected(self):
        a=self.manager.action(self.request(petId=1,newName='AliceNew'))
        b=self.manager.action(self.request(username='bob',petId=1,newName='BobNew'))
        self.assertFalse(a['replayed']);self.assertFalse(b['replayed'])
        before=self.case.rows()
        with self.assertRaises(CityError):self.manager.action(self.request(petId=1,newName='OtherName'))
        self.assertEqual(before,self.case.rows())

    def test_two_simultaneous_submissions_charge_once(self):
        request=self.request(petId=1,newName='AliceNew');before=self.wallet('alice')
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(self.manager.action,[request,request]))
        self.assertEqual(sorted(r['replayed'] for r in results),[False,True])
        self.assertEqual(self.wallet('alice'),(before[0]-3000,before[1]))

    def test_city_and_checkpoint_fences_apply_even_to_replays(self):
        request=self.request(petId=1,newName='AliceNew');self.manager.action(request)
        with transaction(self.case.path) as db:
            db.execute("INSERT INTO battle_checkpoint_members(account,match_id,owner_id) VALUES ('alice','op-test-match',1)")
        before=self.case.rows()
        with self.assertRaises(CityError):self.manager.action(request)
        self.assertEqual(before,self.case.rows())

    def test_operation_context_requires_existing_correct_database(self):
        command=prepare_service('service_rename','operation-tests-0001',dict(petId=1,newName='AliceNew'))
        before=self.case.rows()
        with closing(sqlite3.connect(self.case.path)) as db:
            with self.assertRaises(RuntimeError):execute_service(command,db=db,path=self.case.path,
                helper=self.manager.helper,owner='alice',allowed=True)
        with transaction(self.case.path) as db:
            with self.assertRaises(RuntimeError):execute_service(command,db=db,path=Path(self.case.path).with_name('other.sqlite3'),
                helper=self.manager.helper,owner='alice',allowed=True)
            with self.assertRaises(ServiceRejected):execute_service(command,db=db,path=self.case.path,
                helper=self.manager.helper,owner='alice',allowed=False)
        with transaction(Path(self.case.path).with_name('other.sqlite3')) as db:
            with self.assertRaises(RuntimeError):execute_service(command,db=db,path=self.case.path,
                helper=self.manager.helper,owner='alice',allowed=True)
        self.assertEqual(before,self.case.rows())

    def test_command_fields_immutable_and_internal_alias_not_exposed_to_http(self):
        args=dict(petId=1,newName='AliceNew')
        command=prepare_service('service_rename','operation-tests-0001',args)
        args['petId']=999
        self.assertEqual(command.arguments['petId'],1)
        for fields in (dict(petId=True,newName='AliceNew'),dict(petId=1,newName='AliceNew',owner='bob')):
            with self.assertRaises(ServiceRejected):prepare_service('service_rename','operation-tests-0001',fields)
        with self.assertRaises(CityError):validate(self.request('service_rename_command',command='/changename Alice NewAlice'),action=True)

    def test_warehouse_purchase_uses_pipeline_and_retains_shared_clan_state(self):
        with transaction(self.case.path) as db:db.execute("UPDATE wallets SET credits=50000 WHERE account='alice'")
        request=self.request('warehouse_purchase',service=3,wanted=1,expectedClan=1)
        result=self.manager.action(request);replay=self.manager.action(request)
        self.assertEqual(result['receipt']['creditsDelta'],-15000)
        self.assertTrue(replay['replayed'])
        bob=self.manager.status(dict(username='bob',slot=1))
        self.assertEqual(bob['clanWarehouse']['services'][0]['capacity'],40)
        self.assertEqual(self.wallet('alice')[0],35000)

    def test_private_http_uses_pipeline_without_changing_public_reply_shape(self):
        http=CityHTTP(self.case.router,fixture.KEY,port=0,operations=self.case.ops).start()
        self.addCleanup(http.close)
        url='http://127.0.0.1:'+str(http.http.server_port)+'/v2/services/action'
        payload=self.request(petId=1,newName='AliceNew')
        with patch.object(SERVICE_OPERATIONS,'execute',wraps=SERVICE_OPERATIONS.execute) as execute:
            with urlopen(Request(url,data=json.dumps(payload).encode(),headers={
                'Content-Type':'application/json','Authorization':'Bearer '+fixture.KEY}),timeout=5) as response:
                result=json.loads(response.read())
            self.assertEqual(execute.call_count,1)
        self.assertEqual(set(result),{'status','receipt','replayed'})
        self.assertEqual(set(result['receipt']),{'requestId','action','creditsDelta','goldDelta'})


if __name__=='__main__':unittest.main()
