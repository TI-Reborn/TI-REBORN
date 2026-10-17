import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import verify_clan_warfare_candidate as qa


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.production=self.root/'production';self.candidate=self.root/'candidate'
        self.production.mkdir();self.candidate.mkdir()
        for name in qa.COPY_DIRS:
            (self.production/name).mkdir();(self.production/name/'original.txt').write_bytes(b'old source')

    def bundle(self,rows):
        archive=self.root/'candidate.tar.gz'
        with tarfile.open(archive,'w:gz') as tar:
            for name,data in rows:
                row=tarfile.TarInfo(name);row.size=len(data);tar.addfile(row,io.BytesIO(data))
        sums={n:hashlib.sha256(data).hexdigest() for n,data in rows}
        return archive,dict(member_sha256=sums,runtime_sha256={n:h for n,h in sums.items() if not n.startswith('tests/')},bundle_sha256=qa.digest(archive))

    def test_owned_evidence_copy_and_overlay_leave_original_bytes_unchanged(self):
        old=self.production/'evidence/zones_diagnostic.xml';old.write_bytes(b'<towns><old/></towns>')
        copied=qa.copy_production(self.production,self.candidate)
        bundle,manifest=self.bundle([('evidence/zones_diagnostic.xml',b'<towns><new/></towns>'),('tests/test_example.py',b'pass\n')])
        qa.extract_pinned(bundle,self.candidate,manifest)
        self.assertEqual(old.read_bytes(),b'<towns><old/></towns>')
        self.assertEqual((self.candidate/'evidence/zones_diagnostic.xml').read_bytes(),b'<towns><new/></towns>')
        self.assertIn('actual copied',copied['evidence'])
        self.assertFalse(any(p.is_symlink() for p in self.candidate.rglob('*')))

    def test_symlinked_production_evidence_is_rejected_before_copy(self):
        with patch.object(Path,'is_symlink',lambda p:p==self.production/'evidence'):
            with self.assertRaisesRegex(ValueError,'linked'):qa.copy_production(self.production,self.candidate)
        self.assertEqual((self.production/'evidence/original.txt').read_bytes(),b'old source')

    def test_tampered_archive_and_member_checksum_refuse_overlay(self):
        archive,manifest=self.bundle([('tio/example.py',b'pass\n')])
        manifest['member_sha256']['tio/example.py']='0'*64
        with self.assertRaisesRegex(ValueError,'checksum'):qa.extract_pinned(archive,self.candidate,manifest)
        self.assertFalse((self.candidate/'tio/example.py').exists())
        manifest['bundle_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'archive checksum'):qa.extract_pinned(archive,self.candidate,manifest)

    def test_path_escape_duplicate_and_link_members_rejected(self):
        for name in ('../escape.py','/absolute.py','tio\\bad.py','tio//bad.py'):
            with self.subTest(name=name),self.assertRaises(ValueError):qa.relative_name(name)
        archive,manifest=self.bundle([('tio/example.py',b'a'),('tio/example.py',b'b')])
        with self.assertRaisesRegex(ValueError,'membership'):qa.extract_pinned(archive,self.candidate,manifest)
        archive=self.root/'linked.tar.gz'
        with tarfile.open(archive,'w:gz') as tar:
            row=tarfile.TarInfo('tio/example.py');row.type=tarfile.SYMTYPE;row.linkname='/opt/tio-emulator/tio/example.py';tar.addfile(row)
        manifest=dict(member_sha256={'tio/example.py':'0'*64},runtime_sha256={},bundle_sha256=qa.digest(archive))
        with self.assertRaisesRegex(ValueError,'Non-regular'):qa.extract_pinned(archive,self.candidate,manifest)

    def test_copy_bounds_and_no_player_data_tree(self):
        (self.production/'data').mkdir();(self.production/'data/reservation.sqlite3').write_bytes(b'players')
        qa.copy_production(self.production,self.candidate)
        self.assertFalse((self.candidate/'data').exists())
        with patch.object(qa,'MAX_TOTAL',1):
            with self.assertRaisesRegex(ValueError,'bounds'):qa.copy_production(self.production,self.candidate)

    def test_prepare_is_local_source_pinned_and_does_not_include_credentials(self):
        project=self.root/'project';(project/'tio').mkdir(parents=True);(project/'tests').mkdir()
        (project/'tio/alliances.py').write_text('pass\n');(project/'tests/test_example.py').write_text('pass\n')
        (project/'tests/private.json').write_text('{"password":"private"}')
        selected=project/'selection.json';selected.write_text(json.dumps(['tio/alliances.py']))
        output=project/'reports/clan-warfare/candidate'
        with patch.object(qa,'ROOT',project):
            report=qa.prepare(selected,output)
            with self.assertRaises(ValueError):qa.prepare(selected,output)
        manifest=json.loads((output/'manifest.json').read_text())
        self.assertEqual(report['runtime_files'],1)
        self.assertEqual(set(manifest['member_sha256']),{'tio/alliances.py','tests/test_example.py'})
        self.assertEqual(manifest['runtime_sha256']['tio/alliances.py'],qa.digest(project/'tio/alliances.py'))

    def test_run_pins_child_sources_and_does_not_accept_posttest_candidate_changes(self):
        (self.production/'tio/example.py').write_bytes(b'pass\n')
        bundle,manifest=self.bundle([('tio/example.py',b'candidate=True\n')])
        manifest.update(version=1,modules=list(qa.MODULES))
        proof=self.root/'manifest.json';proof.write_text(json.dumps(manifest))
        for tamper in (False,True):
            def child(command,**kwargs):
                self.assertEqual(kwargs['env']['PYTHONDONTWRITEBYTECODE'],'1')
                self.assertTrue(Path(kwargs['cwd']).is_relative_to(self.root))
                self.assertNotEqual(Path(kwargs['cwd']),self.production)
                if tamper:(Path(kwargs['cwd'])/'tio/example.py').write_bytes(b'changed after tests')
                return SimpleNamespace(returncode=0,stdout='tests passed',stderr='')
            with self.subTest(tamper=tamper),patch.object(qa.subprocess,'run',side_effect=child):
                report=qa.run(bundle,proof,production=self.production,work_parent=self.root)
            self.assertEqual(report['passed'],not tamper)
            self.assertEqual(report['runtime_source_parity'],not tamper)
            self.assertTrue(report['production_selected_sources_unchanged'])
            self.assertEqual((self.production/'tio/example.py').read_bytes(),b'pass\n')


if __name__=='__main__':unittest.main()
