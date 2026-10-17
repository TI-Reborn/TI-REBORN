from contextlib import closing, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from server.accounts import Accounts
from tools.prepare_contracts_local import (ACCOUNTS, BINARIES, CREATOR, MARKER,
                                           PROOF, SETTINGS, digest, prepare)


class PrepareContractsLocalTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.source = self.root / 'reports/arena-surroundings-implementation/client-qa/game-a'
        self.source.mkdir(parents=True)
        self.config = self.root / 'config/contracts-local.toml'
        self.config.parent.mkdir()
        self.config.write_text('bind_address="127.0.0.1"\nadvertised_address="127.0.0.1"\n'
                               'game_port=28512\nsession_port=28513\ndata_directory="../data/contracts-local"\n'
                               'log_level="ERROR"\nmulti_account=true\ncontracts_enabled=true\n')
        resources = {name: ('private-' + name).encode() for name in BINARIES}
        resources.update({'base/config.cfg': b'orange_addr 185.184.42.88\norange_port 28512\n',
                          'base/autoexec.cfg': b'orange_addr 185.184.42.88\norange_port 28512\n',
                          'base/serverlist.cfg': b'<QA Hosted> gameserver\n',
                          'base/gui/icons.png': b'immutable-art-fixture',
                          'base/ground.xml': b'<ground/>',
                          'base/shared config/zones.xml': b'<private-cache/>',
                          'base/shared config/skills.xml': b'<progress-cache/>',
                          'base/credentials.cfg': b'login ignored-personal-source-value'})
        rows = []
        for relative, data in resources.items():
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            rows.append(dict(path=relative, qa_sha256=hashlib.sha256(data).hexdigest(), qa_size=len(data)))
        (self.source / 'log.txt').write_text('personal game log excluded')
        (self.source / 'login.ini').write_text('personal login excluded')
        metadata = dict(schema=1, creator='tools/prepare_hosted_graphical_qa.py', game_root=str(self.source),
                        manifest_files=len(rows), manifest_version='fixture', files=rows,
                        native_pins={name: digest(self.source / name) for name in ('ti.exe', 'orange.dll', 'silver.dll')})
        (self.source / 'qa-client-provenance.json').write_text(json.dumps(metadata))
        (self.source / '.tio-owned-qa').write_text(json.dumps(dict(schema=1, creator=metadata['creator'], root=str(self.source))))

    def database_rows(self):
        path = self.root / 'data/contracts-local/reservation.sqlite3'
        with closing(sqlite3.connect(path)) as db:
            names = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            return {name: db.execute('SELECT * FROM ' + name + ' ORDER BY rowid').fetchall() for name in names}

    def test_copies_only_verified_resources_and_loopback_configs_are_private(self):
        before = {path.relative_to(self.source).as_posix(): digest(path) for path in self.source.rglob('*') if path.is_file()}
        result = prepare(self.root)
        self.assertEqual(result['network_requests'], 0)
        self.assertFalse(result['graphical_validation'])
        self.assertEqual(result['accounts']['created_logins'], ['contract_a', 'contract_b'])
        for suffix in ('a', 'b'):
            copy = self.root / ('reports/contracts-local/clients/game-' + suffix)
            marker = json.loads((copy / MARKER).read_text())
            self.assertEqual(marker['creator'], CREATOR)
            self.assertEqual(marker['root'], str(copy))
            proof = json.loads((copy / PROOF).read_text())
            self.assertEqual(proof['graphical_clients_started'], 0)
            self.assertEqual(proof['personal_files_copied'], 0)
            self.assertFalse((copy / 'base/shared config').exists())
            for relative in ('login.ini', 'log.txt', 'base/credentials.cfg'):
                self.assertFalse((copy / relative).exists())
            for relative in ('base/config.cfg', 'base/autoexec.cfg'):
                self.assertEqual((copy / relative).read_bytes(), SETTINGS)
                self.assertEqual((copy / relative).stat().st_nlink, 1)
                self.assertFalse(os.path.samefile(copy / relative, self.source / relative))
            for relative in (*BINARIES, 'base/ground.xml'):
                self.assertEqual((copy / relative).stat().st_nlink, 1)
                self.assertFalse(os.path.samefile(copy / relative, self.source / relative))
                self.assertEqual(digest(copy / relative), digest(self.source / relative))
            art = next(row for row in proof['files'] if row['path'] == 'base/gui/icons.png')
            if art['method'] == 'verified_immutable_hardlink':
                self.assertTrue(os.path.samefile(copy / art['path'], self.source / art['path']))
            self.assertIn('WorkingDirectory $clientRoot', (copy / 'launch-client.ps1').read_text())
        after = {path.relative_to(self.source).as_posix(): digest(path) for path in self.source.rglob('*') if path.is_file()}
        self.assertEqual(before, after)

    def test_rerun_preserves_account_credentials_saves_and_makes_database_backup(self):
        first = prepare(self.root)
        credentials = Path(first['accounts']['credentials_file'])
        saved_credentials = credentials.read_bytes()
        saved_rows = self.database_rows()
        second = prepare(self.root)
        self.assertEqual(second['accounts']['created_logins'], [])
        self.assertEqual(second['accounts']['preserved_logins'], ['contract_a', 'contract_b'])
        self.assertEqual(credentials.read_bytes(), saved_credentials)
        self.assertEqual(self.database_rows(), saved_rows)
        self.assertTrue(Path(second['accounts']['backup']).is_file())
        accounts = Accounts(self.root / 'data/contracts-local/reservation.sqlite3')
        for line in credentials.read_text().splitlines():
            if not line or line.startswith('#'):
                continue
            login, password, character = line.split('\t')
            self.assertEqual(accounts.verify(login.encode(), password.encode()), login)
            self.assertEqual(character, ACCOUNTS[login])

    def test_existing_account_password_and_wallet_are_not_reset(self):
        first = prepare(self.root)
        database = Path(first['accounts']['database'])
        accounts = Accounts(database)
        accounts.create('contract_a', 'IndependentChangedPassword123!', reset=True)
        with closing(sqlite3.connect(database)) as db, db:
            db.execute('UPDATE wallets SET credits=98765 WHERE account=?', ('contract_a',))
        before = self.database_rows()
        prepare(self.root)
        self.assertEqual(self.database_rows(), before)
        self.assertEqual(accounts.verify(b'contract_a', b'IndependentChangedPassword123!'), 'contract_a')

    def test_source_hash_failure_is_rejected_before_copies_or_accounts(self):
        (self.source / 'silver.dll').write_bytes(b'modified source binary')
        with self.assertRaises(ValueError):
            prepare(self.root)
        self.assertFalse((self.root / 'reports/contracts-local/clients').exists())
        self.assertFalse((self.root / 'data/contracts-local').exists())

    def test_nonempty_unmarked_or_wrong_marker_directory_is_never_adopted(self):
        copy = self.root / 'reports/contracts-local/clients/game-a'
        copy.mkdir(parents=True)
        (copy / 'ti.exe').write_bytes(b'unowned')
        with self.assertRaises(ValueError):
            prepare(self.root)
        self.assertEqual((copy / 'ti.exe').read_bytes(), b'unowned')
        self.assertFalse((copy / MARKER).exists())
        (copy / MARKER).write_text(json.dumps(dict(schema=1, creator='another-tool', root=str(copy))))
        with self.assertRaises(ValueError):
            prepare(self.root)
        self.assertEqual((copy / 'ti.exe').read_bytes(), b'unowned')
        self.assertFalse((self.root / 'data/contracts-local').exists())

    def test_unsafe_config_never_creates_test_clients_or_touches_other_data(self):
        safe = self.config.read_text()
        for before, after in (('127.0.0.1', '185.184.42.88'), ('../data/contracts-local', '../data/standalone'),
                              ('contracts_enabled=true', 'contracts_enabled=false')):
            self.config.write_text(safe.replace(before, after))
            with self.subTest(change=after), self.assertRaises(ValueError):
                prepare(self.root)
            self.assertFalse((self.root / 'reports/contracts-local/clients').exists())
            self.assertFalse((self.root / 'data/contracts-local').exists())
        self.config.write_text(safe)

    def test_mutable_binary_refresh_does_not_write_through_to_source(self):
        prepare(self.root)
        copy = self.root / 'reports/contracts-local/clients/game-a'
        original = digest(self.source / 'silver.dll')
        (copy / 'silver.dll').write_bytes(b'local private corruption')
        self.assertEqual(digest(self.source / 'silver.dll'), original)
        prepare(self.root)
        self.assertEqual(digest(copy / 'silver.dll'), original)
        self.assertFalse(os.path.samefile(copy / 'silver.dll', self.source / 'silver.dll'))

    def test_safe_result_and_stdout_never_contain_generated_passwords(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            result = prepare(self.root)
            print(json.dumps(result))
        credentials = Path(result['accounts']['credentials_file']).read_text()
        rendered = buffer.getvalue()
        for line in credentials.splitlines():
            if not line or line.startswith('#'):
                continue
            password = line.split('\t')[1]
            self.assertFalse(password in rendered, 'Plaintext credential appeared in output')
        self.assertFalse((self.root / 'data/standalone').exists())


if __name__ == '__main__':
    unittest.main()
