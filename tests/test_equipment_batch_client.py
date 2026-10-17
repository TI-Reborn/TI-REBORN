import hashlib
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from deploy.client_equipment_batch import patch,sites,extension,STAGE_ENTRY,OK_ENTRY,BASE_SHA,patch_plan
from verify_auth_native import BINARY
from verify_equipment_batch_native import (candidate,staged,unchanged,wrapped_nonce,hide_cancel,reconstructed_cancel,
    PUBLISHED_BINARY)


class EquipmentBatchClientTests(unittest.TestCase):
    def test_pinned_release_patch_is_idempotent_and_rejects_tampering(self):
        original=BINARY.read_bytes();before=hashlib.sha256(original).hexdigest()
        final=candidate();self.assertEqual(patch(final),final)
        self.assertEqual(hashlib.sha256(PUBLISHED_BINARY.read_bytes()).hexdigest(),BASE_SHA)
        with self.assertRaises(ValueError):patch(original)
        self.assertEqual(hashlib.sha256(BINARY.read_bytes()).hexdigest(),before)
        corrupt=bytearray(final);corrupt[-160]^=1
        with self.assertRaises(ValueError):patch(bytes(corrupt))
        with self.assertRaises(ValueError):patch(b'not a PE')

    def test_all_existing_published_bytes_survive_outside_exact_hook_and_pe_header_sites(self):
        import pefile,struct
        source=PUBLISHED_BINARY.read_bytes();final=candidate()
        self.assertTrue(patch_plan(source,final)['all_other_published_bytes_preserved'])
        pe=pefile.PE(data=final)
        for offset in (pe.sections[-1].get_file_offset()+8,
                       pe.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage')):
            corrupt=bytearray(final);struct.pack_into('<I',corrupt,offset,1)
            with self.subTest(offset=offset),self.assertRaises(ValueError):patch(bytes(corrupt))

    def test_original_x86_weapon_and_armor_stage_then_ok_once(self):
        for kind in (1,9):
            with self.subTest(kind=kind):staged(kind)

    def test_city_and_non_equipment_keep_original_wire(self):
        for battle,kind in ((0,1),(0,9),(1,2),(1,3),(1,12)):
            with self.subTest(battle=battle,kind=kind):unchanged(battle,kind)

    def test_native_nonce_wrap_skips_zero(self):wrapped_nonce()

    def test_native_inventory_hide_cancels_only_own_window_and_reopens_new_batch(self):hide_cancel()

    def test_native_reconstructed_inventory_cancels_previous_lease(self):reconstructed_cancel()


if __name__=='__main__':unittest.main()
