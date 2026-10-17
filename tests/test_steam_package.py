import copy
import unittest
from tools.prepare_steam_package import BINARIES, SEEDS, validate_manifest


class SteamPackageTests(unittest.TestCase):
    def setUp(self):
        self.manifest=dict(schema=1,version='test',files=[dict(path=p,size=1,sha256='a'*64,seed=p in SEEDS)
                           for p in sorted(BINARIES|SEEDS)])

    def test_required_public_client_is_accepted(self):
        self.assertEqual(len(validate_manifest(self.manifest)),8)

    def test_private_and_development_files_are_rejected(self):
        for path in ('base/login.ini','base/notes-user.txt','base/skillbar.dat','base/players.sqlite3','base/secrets.db','base/test.pdb'):
            with self.subTest(path=path):
                m=copy.deepcopy(self.manifest);m['files'].append(dict(path=path,size=1,sha256='a'*64,seed=False))
                with self.assertRaises(ValueError):validate_manifest(m)

    def test_windows_escape_alias_and_device_paths_are_rejected(self):
        for path in ('base/../private','base/CON','base/config.cfg:secret','base/other.','base\\other','/base/file','base//file'):
            with self.subTest(path=path):
                m=copy.deepcopy(self.manifest);m['files'].append(dict(path=path,size=1,sha256='a'*64,seed=False))
                with self.assertRaises(ValueError):validate_manifest(m)

    def test_seed_policy_and_duplicate_identity_are_rejected(self):
        m=copy.deepcopy(self.manifest);m['files'][0]['seed']=not m['files'][0]['seed']
        with self.assertRaises(ValueError):validate_manifest(m)
        m=copy.deepcopy(self.manifest);m['files'].append(copy.deepcopy(m['files'][0]))
        with self.assertRaises(ValueError):validate_manifest(m)

    def test_missing_native_binary_and_invalid_size_hash_are_rejected(self):
        m=copy.deepcopy(self.manifest);m['files']=[r for r in m['files'] if r['path']!='ti.exe']
        with self.assertRaises(ValueError):validate_manifest(m)
        for key,value in (('size',-1),('size',True),('sha256','not-a-checksum')):
            m=copy.deepcopy(self.manifest);m['files'][0][key]=value
            with self.assertRaises(ValueError):validate_manifest(m)


if __name__=='__main__':unittest.main()
