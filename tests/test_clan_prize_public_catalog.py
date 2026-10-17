"""Pending clan prizes must use the shipped catalogue and remain owner isolated."""
import unittest
import test_clan_benefits as fixture
from tio import clan_benefits
from tio.db_transaction import transaction
from tio.warehouse import WarehouseStore

class PublicCataloguePrizeTests(unittest.TestCase):
    def setUp(self):
        self.case=fixture.ClanBenefitTests(methodName='runTest')
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)

    def test_subgrenade_and_lighttrainer_preserved_delivery_and_replay(self):
        with transaction(self.case.path) as db:
            db.execute("INSERT INTO clan_assault_prizes VALUES ('pending-grenade','alice',340,1,0)")
            db.execute("INSERT INTO clan_assault_prizes VALUES ('pending-trainer','alice',5003,1,0)")
        self.assertEqual(self.case.call(clan_benefits.deliver_prizes,'alice',capacity=0),())
        self.assertEqual(self.case.read("SELECT delivered FROM clan_assault_prizes WHERE account='alice'"),[(0,),(0,)])
        packets=self.case.call(clan_benefits.deliver_prizes,'alice',capacity=10)
        self.assertTrue(packets)
        items=WarehouseStore(self.case.path).items('alice')
        self.assertEqual({i.template_id for i in items},{340,5003})
        self.assertEqual(len({i.instance_id for i in items}),2)
        before=self.case.read("SELECT * FROM warehouse_items WHERE account='alice'")
        self.assertEqual(self.case.call(clan_benefits.deliver_prizes,'alice',capacity=10),())
        self.assertEqual(self.case.read("SELECT * FROM warehouse_items WHERE account='alice'"),before)
        self.assertEqual(WarehouseStore(self.case.path).items('bob'),())

if __name__=='__main__':unittest.main()
