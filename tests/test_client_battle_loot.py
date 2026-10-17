from pathlib import Path
import unittest
import pefile
from deploy.client_battle_loot import patch,HOOK,code
from deploy.client_upgrade_kit import patch as kit

CLIENT=Path(r'C:\Program Files (x86)\TIOnline\silver.dll')


class BattleLootClientTests(unittest.TestCase):
    def test_unknown_binary_rejected(self):
        with self.assertRaises(ValueError):patch(b'unknown executable')

    @unittest.skipUnless(CLIENT.exists(),'original client unavailable')
    def test_only_ground_transfer_hook_changes_previous_release(self):
        base=kit(CLIENT.read_bytes());result=patch(base)
        self.assertEqual(patch(result),result)
        self.assertEqual(result[len(base):],code())
        pe=pefile.PE(data=base);section=pe.sections[-1]
        hook=pe.get_offset_from_rva(HOOK-0x400000)
        allowed=set(range(hook,hook+5))
        for offset in (8,16):allowed.update(range(section.get_file_offset()+offset,section.get_file_offset()+offset+4))
        self.assertTrue({i for i,(a,b) in enumerate(zip(base,result)) if a!=b}<=allowed)
        corrupted=bytearray(result);corrupted[hook+1]^=1
        with self.assertRaises(ValueError):patch(bytes(corrupted))
