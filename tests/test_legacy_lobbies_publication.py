"""Scoped release guards; synthetic fixtures do not count as gameplay QA."""
import copy
import json
from pathlib import Path
import unittest

from tools import publish_legacy_lobbies_client as release

p = release.PUBLISHER


class LegacyPublicationGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old = release.BASELINE.read_bytes()
        cls.source = release.BASELINE.parent.joinpath('silver.dll').read_bytes()
        raw = bytearray(cls.source)
        raw[0x20] ^= 1  # A declared DOS-stub fixture change; no real release.
        cls.candidate = bytes(raw)
        cls.review = dict(changes=[dict(offset=0x20,size=1,
             source_sha256=p.sha(cls.source[0x20:0x21]),
             candidate_sha256=p.sha(cls.candidate[0x20:0x21]),
             purpose='Synthetic guard fixture')],appended_size=0,appended_sha256=p.sha(b''))
        cls.package = dict(schema=1,previous_version=release.PREVIOUS_VERSION,
             version=release.VERSION,baseline_manifest_sha256=release.MANIFEST_SHA,
             selection=dict(fix=release.FIX),native_review=cls.review,
             files=[dict(path='silver.dll',source='silver.dll',sha256=p.sha(cls.candidate),
                         size=len(cls.candidate),kind='native')])
        new = json.loads(cls.old)
        new['version'] = release.VERSION
        next(r for r in new['files'] if r['path']=='silver.dll').update(
                  sha256=p.sha(cls.candidate),size=len(cls.candidate))
        cls.new = (json.dumps(new,ensure_ascii=False,indent=2)+'\n').encode()

    def test_exact_scope_preserves_all_other_records(self):
        scope = p.manifest_transition(self.old,self.new,self.package)
        self.assertEqual(scope['changed'],['silver.dll'])
        self.assertEqual(scope['preserved_records'],6566)
        self.assertEqual(scope['added'],[])
        p.native_preserved(self.source,self.candidate,self.review)

    def test_other_resource_and_selection_rejected(self):
        for change in ('ti','extra','selection'):
            package = copy.deepcopy(self.package)
            if change=='ti':package['files'][0]['path']='ti.exe'
            elif change=='extra':package['files'].append(copy.deepcopy(package['files'][0]))
            else:package['selection']['fix']='unrelated-work'
            raw = json.dumps(package).encode()
            with self.assertRaises(ValueError):p.package_identity(raw,p.sha(raw))

    def test_unrelated_manifest_record_and_seed_rejected(self):
        for change in ('other','seed'):
            manifest = json.loads(self.new)
            record = next(r for r in manifest['files'] if r['path']==('silver.dll' if change=='seed' else 'ti.exe'))
            record['seed'] = True
            raw = json.dumps(manifest).encode()
            with self.assertRaises(ValueError):p.manifest_transition(self.old,raw,self.package)

    def test_undeclared_native_bytes_rejected(self):
        raw = bytearray(self.candidate)
        raw[0x21] ^= 1
        with self.assertRaises(ValueError):p.native_preserved(self.source,bytes(raw),self.review)

    def test_native_authentication_change_rejected_even_if_declared(self):
        import pefile
        image = pefile.PE(data=self.source)
        try:offset=image.get_offset_from_rva(p.AUTH_SPANS[0][0]-0x400000)
        finally:image.close()
        raw = bytearray(self.candidate)
        raw[offset] ^= 1
        review = copy.deepcopy(self.review)
        review['changes'].append(dict(offset=offset,size=1,
             source_sha256=p.sha(self.source[offset:offset+1]),
             candidate_sha256=p.sha(bytes(raw[offset:offset+1])),purpose='Declared auth tamper fixture'))
        with self.assertRaises(ValueError):p.native_preserved(self.source,bytes(raw),review)


if __name__ == '__main__':
    unittest.main()
