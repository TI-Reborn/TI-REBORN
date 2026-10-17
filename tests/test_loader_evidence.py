"""Independent checks on the captured initializer failure and recovery evidence."""
import json
import struct
import unittest
import zlib
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def events(name):
    result=[]
    for line in (ROOT/'evidence'/name).read_text(encoding='utf-8-sig').splitlines():
        if line.startswith('{'):
            obj=json.loads(line)
            result.append(obj.get('payload',obj))
    return result

class LoaderEvidenceTests(unittest.TestCase):
    def test_api_hashes(self):
        self.assertEqual(zlib.crc32(b'GetCursorPos'),0x89606806)
        self.assertEqual(zlib.crc32(b'CreateFileA'),0x553b5c78)
        self.assertEqual(zlib.crc32(b'DeleteCriticalSection'),0xa3589103)

    def test_control_lookup_failed(self):
        rows=events('resolver_run.log')
        lookup=[r for r in rows if r.get('event')=='resolve_leave' and r['args'][1]=='0x89606806']
        self.assertEqual(len(lookup),1)
        self.assertEqual(lookup[0]['result'],'0x0')
        self.assertTrue(any(r.get('event')=='LoadLibraryW' and r.get('lastError')==1114 and r['result']=='0x0' for r in rows))

    def test_two_recovery_runs(self):
        for name in ('user32_fix_run.log','user32_fix_run2.log'):
            with self.subTest(name=name):
                rows=events(name)
                fix=next(r for r in rows if r.get('event')=='user32_slot_fix')
                lookup=next(r for r in rows if r.get('event')=='resolve_leave' and r['args'][1]=='0x89606806')
                self.assertEqual(lookup['args'][0],fix['after'])
                self.assertNotEqual(lookup['result'],'0x0')
                self.assertTrue(any(r.get('event')=='LoadLibraryW' and r['result']!='0x0' for r in rows))

    def test_unpacked_export_targets(self):
        directory=ROOT/'evidence/loader-user32-fix'
        metadata=json.loads((directory/'orange.mapped.json').read_text())
        image=(directory/'orange.mapped.bin').read_bytes()
        region=json.loads((directory/'unpacked-0xc9b0000.json').read_text())
        unpacked=(directory/'unpacked-0xc9b0000.bin').read_bytes()
        base=int(metadata['base'],16); ub=int(region['base'],16)
        self.assertEqual(len(unpacked),region['size'])
        self.assertEqual(len(metadata['exports']),11)
        for exp in metadata['exports']:
            offset=int(exp['address'],16)-base
            self.assertEqual(image[offset],0xe9)
            target=base+offset+5+struct.unpack_from('<i',image,offset+1)[0]
            self.assertTrue(ub<=target<ub+len(unpacked))
        # Getter and initialization-key check, original instructions in unpacked code.
        self.assertEqual(unpacked[0x15d0],0xb8)
        self.assertEqual(unpacked[0x1620:0x1627],bytes.fromhex('66817c240431d4'))
