import hashlib
from pathlib import Path
import unittest
import pefile
from deploy.client_upgrade_kit import patch,SITES,BASE_SHA
from deploy.client_character_onboarding import patch as onboarding

CLIENT=Path(r'C:\Program Files (x86)\TIOnline\silver.dll')


class UpgradeKitClientTests(unittest.TestCase):
    def test_unknown_binary_rejected(self):
        with self.assertRaises(ValueError):patch(b'unknown executable')

    @unittest.skipUnless(CLIENT.exists(),'original client unavailable')
    def test_persistent_fix_preserves_existing_release_and_rejects_foreign_changes(self):
        original=CLIENT.read_bytes();base=onboarding(original);result=patch(base)
        self.assertEqual(hashlib.sha256(base).hexdigest(),BASE_SHA)
        self.assertEqual(patch(original),result)
        self.assertEqual(patch(result),result)
        self.assertEqual(len(base),len(result))
        pe=pefile.PE(data=base);expected=set()
        for va,old,new in SITES:
            offset=pe.get_offset_from_rva(va-0x400000)
            self.assertEqual(result[offset:offset+len(new)],new)
            expected.update(offset+i for i,(a,b) in enumerate(zip(old,new)) if a!=b)
        self.assertEqual({i for i,(a,b) in enumerate(zip(base,result)) if a!=b},expected)
        self.assertEqual(len(expected),6)
        damaged=bytearray(result);damaged[-1]^=1
        with self.assertRaises(ValueError):patch(bytes(damaged))
