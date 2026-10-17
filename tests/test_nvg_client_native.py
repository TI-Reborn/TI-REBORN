"""Native regressions for safe zero-AP NVG deactivation and F9 state."""
import hashlib
import sys
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from deploy import client_battle_items as client
from verify_nvg_client_native import (SOURCE,candidate,receiver_cases,gate_case,
                                      inventory_cases,prior_sc_cases,snapshot,scene_for,stored,cached_original_emulator)
import verify_battle_item_client_native as items


class NVGClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.before=SOURCE.read_bytes();cls.after=candidate()

    def test_exact_published_release_and_idempotence(self):
        self.assertEqual(hashlib.sha256(self.before).hexdigest(),client.NVG_BASE_SHA)
        self.assertEqual(client.patch_nvg(self.after),self.after)
        plan=client.nvg_patch_plan(self.before,self.after)
        self.assertTrue(plan['all_other_published_bytes_preserved'])
        self.assertTrue(plan['existing_f6_f7_f8_code_preserved'])
        self.assertEqual(plan['appended_bytes'],4096)

    def test_unknown_base_candidate_hook_and_appended_code_rejected(self):
        for data,offset in ((self.before,2000),(self.after,2000),(self.after,-100),
                            (self.after,client.nvg_patch_plan(self.before,self.after)['changes'][1]['offset'])):
            damaged=bytearray(data);damaged[offset]^=1
            with self.subTest(offset=offset),self.assertRaises(ValueError):client.patch_nvg(bytes(damaged))
        with self.assertRaises(ValueError):client.patch_nvg(b'not a PE')

    def test_full_snapshot_bounds_sort_ids_malformed_clear_and_aslr(self):
        for base in (0x400000,0x500000):receiver_cases(self.after,base)

    def test_only_active_owned_nvg_bypasses_original_ap_gate(self):
        for base in (0x400000,0x500000):
            for ap in (0,1,2,3,10):
                for ids in ((),(17,),(18,)):
                    with self.subTest(base=base,ap=ap,ids=ids):gate_case(self.after,base=base,ap=ap,ids=ids)
            for template in (35,5003,5011,5012):gate_case(self.after,base=base,template=template)
            gate_case(self.after,base=base,actor=18,ids=(17,))
            gate_case(self.after,base=base,battle=0)

    def test_shortcut_consumed_before_repeated_click_then_server_restores(self):
        for base in (0x400000,0x500000):
            for ap in range(3):gate_case(self.after,base=base,ap=ap,repeat=2)

    def test_whole_original_inventory_turn_guard_ap_rejections_and_native33(self):
        with patch.object(items,'emulator',cached_original_emulator):inventory_cases(self.after)

    def test_f8_f7_and_original_bd_callbacks_survive(self):
        for base in (0x400000,0x500000):prior_sc_cases(self.after,base)

    def test_authoritative_empty_snapshot_removes_previous_battle_actor(self):
        scene=scene_for(self.after,0x400000)
        scene.dispatch(snapshot((17,)));self.assertEqual(stored(scene),(17,))
        scene.dispatch(snapshot(()));self.assertEqual(stored(scene),())


if __name__=='__main__':unittest.main()
