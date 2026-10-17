import json
import unittest
import test_achievements as fixtures
from tio.achievements import catalog
from tio.protocol.item_list import decode_item_list
from tio.warehouse import WarehouseStore


class CompletedItemPrizesTests(unittest.TestCase):
    setUp=fixtures.AchievementTests.setUp
    query=fixtures.AchievementTests.query
    progress=fixtures.AchievementTests.progress
    earned=fixtures.AchievementTests.earned

    def test_throwing_delivers_all_three_actual_manual_rewards_once(self):
        self.progress(add={'throwing_kills':10});self.store.flush('alice')
        items=WarehouseStore(self.path).items('alice')
        from collections import Counter
        counts=Counter()
        for item in items:counts[item.template_id,item.unknown_bytes_02[0]]+=item.count
        self.assertEqual(counts,{(317,1):1,(320,0):3,(340,1):1})
        self.assertFalse(self.store.flush('alice'))
        self.assertEqual(WarehouseStore(self.path).items('alice'),items)

    def test_trainer_is_real_item_without_credit_substitute(self):
        before=self.wallet.ensure('alice').credits
        self.progress(add={'crates':1000});self.store.flush('alice')
        items=WarehouseStore(self.path).items('alice')
        self.assertEqual(sum(i.count for i in items if i.template_id==5003),1)
        self.assertEqual(self.wallet.ensure('alice').credits,before)
        self.assertFalse(self.store.flush('alice'))

    def test_existing_immutable_legacy_snapshot_is_not_reawarded(self):
        from tio.db_transaction import transaction
        old=next(dict(r) for r in catalog() if r['id']==35)
        old.update(prizes=[],temporary_credits=5000,reward_source='temporary credits',unmapped_prize='LightTrainer')
        with transaction(self.path) as db:
            db.execute('INSERT INTO achievement_awards VALUES (?,?,?,1)',('alice',35,json.dumps(old)))
            db.execute('INSERT INTO achievement_prizes VALUES (?,?,?,1)',('alice',35,0))
        self.progress(add={'crates':1000});before=self.wallet.ensure('alice')
        self.store.flush('alice')
        self.assertEqual(self.wallet.ensure('alice'),before)
        self.assertFalse(any(i.template_id==5003 for i in WarehouseStore(self.path).items('alice')))
        self.assertEqual(json.loads(self.query('SELECT body FROM achievement_awards WHERE id=35')[0][0]),old)


if __name__=='__main__':unittest.main()
