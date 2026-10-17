import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from launcher.build_archive import attach, build, files_digest


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.blobs=self.root/'blobs';self.blobs.mkdir()
        self.data=b'client resource\n'*8192;self.sha=hashlib.sha256(self.data).hexdigest()
        (self.blobs/self.sha).write_bytes(self.data)
        self.manifest=dict(schema=1,version='test',files=[dict(path='ti.exe',size=len(self.data),sha256=self.sha),
            dict(path='base/resource.dat',size=len(self.data),sha256=self.sha,seed=False)])

    def test_zip_deduplicates_and_compresses_verified_blobs(self):
        descriptor=build(self.manifest,self.blobs,self.root/'client.zip')
        self.assertLess(descriptor['size'],len(self.data)//10)
        self.assertEqual(descriptor['sha256'],hashlib.sha256((self.root/'client.zip').read_bytes()).hexdigest())
        with zipfile.ZipFile(self.root/'client.zip') as archive:
            self.assertEqual(archive.namelist(),[self.sha]);self.assertEqual(archive.read(self.sha),self.data)

    def test_deterministic_and_binding_ignores_metadata_and_record_order(self):
        first=build(self.manifest,self.blobs,self.root/'a.zip')
        other={**self.manifest,'files':list(reversed(self.manifest['files'])),'news':'changed'}
        self.assertEqual(first,build(other,self.blobs,self.root/'b.zip'))
        self.assertEqual(first['filesSha256'],files_digest(other))
        changed={**self.manifest,'files':[{**self.manifest['files'][0],'seed':True},self.manifest['files'][1]]}
        self.assertNotEqual(first['filesSha256'],files_digest(changed))

    def test_corrupt_blob_rejected(self):
        (self.blobs/self.sha).write_bytes(b'x'*len(self.data))
        with self.assertRaises(ValueError):build(self.manifest,self.blobs,self.root/'bad.zip')

    def test_invalid_hash_size_and_conflicting_duplicates_rejected(self):
        for change in ({'sha256':'../escape'},{'size':-1},{'size':True},{'size':len(self.data)-1}):
            invalid={**self.manifest,'files':[self.manifest['files'][0],{**self.manifest['files'][1],**change}]}
            with self.subTest(change=change),self.assertRaises(ValueError):build(invalid,self.blobs,self.root/'bad.zip')

    def test_no_overwrite_and_no_player_files(self):
        destination=self.root/'client.zip';destination.write_bytes(b'existing')
        with self.assertRaises(FileExistsError):build(self.manifest,self.blobs,destination)
        self.assertEqual(destination.read_bytes(),b'existing')
        (self.root/'login.ini').write_text('personal password')
        (self.root/'manifest.json').write_text(json.dumps(self.manifest))
        destination.unlink();descriptor=attach(self.root)
        updated=json.loads((self.root/'manifest.json').read_text())
        self.assertEqual(updated,{**self.manifest,'archive':descriptor})
        with zipfile.ZipFile(self.blobs/descriptor['sha256']) as archive:self.assertEqual(archive.namelist(),[self.sha])


if __name__=='__main__':unittest.main()
