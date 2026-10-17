import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools.prepare_contracts_local import BINARIES, CREATOR, MARKER, PROOF, SETTINGS, SOURCE_CREATOR, SOURCE_PROOF, digest
from tools import prepare_contracts_city_local as city


def sha(data):
    return hashlib.sha256(data).hexdigest()


class PrepareContractsCityLocalTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / city.SOURCE
        self.source.mkdir(parents=True)
        # The frame fixture deliberately starts as an immutable hardlink. This
        # proves replacements cannot edit the verified QA source through it.
        self.resources = {name: ('original-native-' + name).encode() for name in BINARIES}
        self.resources.update({'base/pda/contracts_frame.png': b'old-immutable-frame',
                               'base/config.cfg': SETTINGS,
                               'base/autoexec.cfg': SETTINGS,
                               'base/gui/unchanged.png': b'untouched-art'})
        source_rows = []
        for relative, value in self.resources.items():
            file = self.source / relative
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(value)
            source_rows.append(dict(path=relative, qa_sha256=sha(value), qa_size=len(value)))
        source_proof = dict(schema=1, creator=SOURCE_CREATOR, game_root=str(self.source),
                            manifest_files=len(source_rows), files=source_rows,
                            native_pins={name: digest(self.source / name) for name in ('ti.exe', 'orange.dll', 'silver.dll')})
        (self.source / SOURCE_PROOF).write_bytes(city.data_json(source_proof))
        (self.source / '.tio-owned-qa').write_bytes(city.data_json(dict(schema=1, creator=SOURCE_CREATOR, root=str(self.source))))
        self.before_proofs = {}
        for relative in city.CLIENTS:
            folder = self.root / relative
            folder.mkdir(parents=True)
            (folder / MARKER).write_bytes(city.data_json(dict(schema=1, creator=CREATOR, root=str(folder))))
            rows = []
            for resource, value in self.resources.items():
                file = folder / resource
                file.parent.mkdir(parents=True, exist_ok=True)
                if resource.endswith('.png'):
                    os.link(self.source / resource, file)
                else:
                    file.write_bytes(value)
                rows.append(dict(path=resource, sha256=sha(value), size=len(value), source_sha256=sha(value), method='fixture'))
            proof = dict(schema=1, creator=CREATOR, root=str(folder), source=str(self.source),
                         source_provenance=dict(path=str(self.source / SOURCE_PROOF), sha256=digest(self.source / SOURCE_PROOF)),
                         endpoint='127.0.0.1:28512', resources=len(rows), files=rows, methods={'fixture': len(rows)})
            self.before_proofs[relative] = city.data_json(proof)
            (folder / PROOF).write_bytes(self.before_proofs[relative])
        self.package = self.root / city.PACKAGE
        self.package.mkdir(parents=True)
        rows = []
        for resource in sorted(city.FILES):
            value = ('reviewed-city-payload-' + resource).encode()
            file = self.package / resource
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(value)
            old = self.resources.get(resource)
            rows.append(dict(path=resource, sha256=sha(value), size=len(value),
                             before_sha256=sha(old) if old else None, before_size=len(old) if old else None))
        silver = next(row for row in rows if row['path'] == 'silver.dll')
        self.manifest = dict(schema=1, overlay_id=city.OVERLAY_ID, files=rows,
                             native_pins={'silver.dll': dict(before_sha256=silver['before_sha256'], after_sha256=silver['sha256'])})
        (self.package / 'overlay-manifest.json').write_bytes(city.data_json(self.manifest))
        plan = self.root / city.PLAN
        plan.parent.mkdir(parents=True)
        plan.write_bytes(city.data_json(dict(source_sha256=silver['before_sha256'], payload_sha256=silver['sha256'])))

    def client(self, suffix='a'):
        return self.root / ('reports/contracts-local/clients/game-' + suffix)

    def source_snapshot(self):
        return {file.relative_to(self.source).as_posix(): city.identity(file)
                for file in self.source.rglob('*') if file.is_file()}

    def assert_original_clients(self):
        for relative in city.CLIENTS:
            folder = self.root / relative
            self.assertEqual((folder / PROOF).read_bytes(), self.before_proofs[relative])
            for resource, value in self.resources.items():
                self.assertEqual((folder / resource).read_bytes(), value)
            for resource in city.FILES - self.resources.keys():
                self.assertFalse((folder / resource).exists())

    def test_dry_run_idempotent_install_and_complete_rollback(self):
        source = self.source_snapshot()
        preview = city.prepare(self.root, dry_run=True)
        self.assertEqual(preview['status'], 'ready')
        self.assertFalse((self.root / city.BACKUPS).exists())
        result = city.prepare(self.root)
        self.assertEqual(result['status'], 'installed')
        self.assertEqual(result['network_requests'], 0)
        self.assertEqual(self.source_snapshot(), source)
        for relative in city.CLIENTS:
            proof = city.verify_client(self.root, relative)
            self.assertEqual(proof[city.OVERLAY_KEY]['backup'], result['backup'])
            for row in self.manifest['files']:
                path = self.root / relative / row['path']
                self.assertEqual(digest(path), row['sha256'])
                self.assertEqual(path.stat().st_nlink, 1)
        second = city.prepare(self.root)
        self.assertEqual(second['status'], 'already_installed')
        self.assertEqual(second['backup'], result['backup'])
        self.assertEqual(len(list((self.root / city.BACKUPS).iterdir())), 1)
        restored = city.rollback(self.root)
        self.assertEqual(restored['status'], 'rolled_back')
        self.assert_original_clients()
        self.assertEqual(self.source_snapshot(), source)
        self.assertEqual(city.rollback(self.root)['status'], 'not_installed')

    def test_hardlinked_frame_is_detached_without_touching_source(self):
        target = self.client() / 'base/pda/contracts_frame.png'
        origin = self.source / 'base/pda/contracts_frame.png'
        self.assertTrue(os.path.samefile(target, origin))
        source = city.identity(origin)
        city.prepare(self.root)
        self.assertFalse(os.path.samefile(target, origin))
        self.assertEqual(city.identity(origin), source)
        self.assertEqual(target.stat().st_nlink, 1)

    def test_second_client_wrong_owner_blocks_all_mutations(self):
        marker = self.client('b') / MARKER
        marker.write_bytes(city.data_json(dict(schema=1, creator='unrelated-tool', root=str(self.client('b')))))
        with self.assertRaisesRegex(ValueError, 'Unowned'):
            city.prepare(self.root)
        self.assert_original_clients()
        self.assertFalse((self.root / city.BACKUPS).exists())

    def test_unrelated_client_hash_change_blocks_before_backups(self):
        changed = self.client('b') / 'silver.dll'
        changed.write_bytes(b'private unexpected native build')
        first = (self.client() / PROOF).read_bytes()
        with self.assertRaisesRegex(ValueError, 'resource changed'):
            city.prepare(self.root)
        self.assertEqual((self.client() / PROOF).read_bytes(), first)
        self.assertEqual(changed.read_bytes(), b'private unexpected native build')
        self.assertFalse((self.root / city.BACKUPS).exists())

    def test_source_hash_change_blocks_before_client_mutations(self):
        (self.source / 'ti.exe').write_bytes(b'unsupported changed source')
        with self.assertRaisesRegex(ValueError, 'Source QA resource changed'):
            city.prepare(self.root)
        self.assert_original_clients()
        self.assertFalse((self.root / city.BACKUPS).exists())

    def test_native_manifest_requires_exact_supported_patch_plan(self):
        plan = self.root / city.PLAN
        metadata = city.read_json(plan)
        metadata['source_sha256'] = 'f' * 64
        plan.write_bytes(city.data_json(metadata))
        with self.assertRaisesRegex(ValueError, 'Unsupported native binary'):
            city.prepare(self.root)
        self.assert_original_clients()
        self.assertFalse((self.root / city.BACKUPS).exists())

    def test_new_texture_collision_is_preserved(self):
        collided = self.client('b') / 'base/pda/contracts_icon.png'
        collided.write_bytes(b'not owned by overlay')
        with self.assertRaisesRegex(ValueError, 'unowned new city resource'):
            city.prepare(self.root)
        self.assertEqual(collided.read_bytes(), b'not owned by overlay')
        self.assertFalse((self.root / city.BACKUPS).exists())

    def test_rollback_refuses_changed_overlay_before_restoring_either_client(self):
        city.prepare(self.root)
        changed = self.client('b') / 'base/pda/contracts_icon.png'
        changed.write_bytes(b'user replaced texture')
        first = digest(self.client() / 'silver.dll')
        with self.assertRaisesRegex(ValueError, 'resource changed; rollback refused'):
            city.rollback(self.root)
        self.assertEqual(digest(self.client() / 'silver.dll'), first)
        self.assertEqual(changed.read_bytes(), b'user replaced texture')

    def test_rollback_refuses_unrelated_managed_change(self):
        city.prepare(self.root)
        # Detach before changing this fixture so source stays intact.
        target = self.client('b') / 'base/gui/unchanged.png'
        city.atomic(target, data=b'user unrelated art')
        first = digest(self.client() / 'silver.dll')
        with self.assertRaisesRegex(ValueError, 'Unrelated client resource changed'):
            city.rollback(self.root)
        self.assertEqual(digest(self.client() / 'silver.dll'), first)
        self.assertEqual(target.read_bytes(), b'user unrelated art')

    def test_path_traversal_and_resource_additions_rejected(self):
        self.manifest['files'][0]['path'] = '../outside.dll'
        (self.package / 'overlay-manifest.json').write_bytes(city.data_json(self.manifest))
        with self.assertRaisesRegex(ValueError, 'precisely'):
            city.prepare(self.root)
        self.assert_original_clients()

    def test_reparse_or_symlink_client_is_rejected(self):
        target = self.client() / 'base/pda'
        target.rename(self.client() / 'base/pda-original')
        if os.name == 'nt':
            result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(target), str(self.source / 'base/pda')],
                                    capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, 'Failed to create scoped fixture junction')
        else:
            target.symlink_to(self.source / 'base/pda', target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'designated directory|filesystem link|reparse'):
            city.prepare(self.root)
        self.assertFalse((self.root / city.BACKUPS).exists())

    def test_interrupted_mutation_automatically_rolls_back_using_private_journal(self):
        original_atomic = city.atomic
        injected = False

        def fail_once(target, **kwargs):
            nonlocal injected
            if (not injected and kwargs.get('source') is not None
                    and Path(kwargs['source']) == self.package / 'base/pda/contracts_icon.png'):
                injected = True
                raise OSError('fixture simulated replace failure')
            return original_atomic(target, **kwargs)

        with patch.object(city, 'atomic', side_effect=fail_once):
            with self.assertRaisesRegex(OSError, 'simulated replace failure'):
                city.prepare(self.root)
        self.assertTrue(injected)
        self.assert_original_clients()
        journal = next((self.root / city.BACKUPS).glob('*/install.json'))
        self.assertEqual(city.read_json(journal)['status'], 'rolled_back')

    def test_corrupt_backup_blocks_rollback_without_overwriting_clients(self):
        result = city.prepare(self.root)
        backup = self.root / result['backup'] / 'game-b/files/silver.dll'
        backup.write_bytes(b'corrupted saved binary')
        first = digest(self.client() / 'silver.dll')
        with self.assertRaisesRegex(ValueError, 'backup changed'):
            city.rollback(self.root)
        self.assertEqual(digest(self.client() / 'silver.dll'), first)

    def test_changed_package_cannot_be_silently_reapplied(self):
        city.prepare(self.root)
        changed = self.package / 'base/pda/contracts_button.png'
        changed.write_bytes(b'unreviewed package')
        first = digest(self.client() / 'silver.dll')
        with self.assertRaisesRegex(ValueError, 'runtime package changed'):
            city.prepare(self.root)
        self.assertEqual(digest(self.client() / 'silver.dll'), first)

    def test_launch_preflight_rejects_changed_overlay_descriptor(self):
        city.prepare(self.root)
        file = self.client() / PROOF
        proof = city.read_json(file)
        proof[city.OVERLAY_KEY]['manifest_sha256'] = '0' * 64
        file.write_bytes(city.data_json(proof))
        with self.assertRaisesRegex(ValueError, 'overlay descriptor differs'):
            city.verify_client(self.root, city.CLIENTS[0])

    def test_launch_preflight_rejects_unrecorded_provenance_edit(self):
        city.prepare(self.root)
        file = self.client() / PROOF
        proof = city.read_json(file)
        proof['unrelated_manual_edit'] = True
        file.write_bytes(city.data_json(proof))
        with self.assertRaisesRegex(ValueError, 'private journal'):
            city.verify_client(self.root, city.CLIENTS[0])

    def test_safe_settings_reconciliation_preserves_config_and_original_backups(self):
        result = city.prepare(self.root)
        backup = self.root / result['backup']
        original = (backup / 'game-a/original-provenance.json').read_bytes()
        applied = (backup / 'game-a/applied-provenance.json').read_bytes()
        target = self.client() / 'base/config.cfg'
        preferences = SETTINGS.replace(b'r_width 1024', b'r_width 1920').replace(b'r_height 768', b'r_height 1080') + b'volume 50\r\n'
        target.write_bytes(preferences)
        with self.assertRaisesRegex(ValueError, 'resource changed'):
            city.verify_client(self.root, city.CLIENTS[0])
        update = city.refresh_settings(self.root)
        self.assertEqual(update['status'], 'settings_verified')
        self.assertEqual(update['config_files_written'], 0)
        self.assertEqual(target.read_bytes(), preferences)
        self.assertEqual((backup / 'game-a/original-provenance.json').read_bytes(), original)
        self.assertEqual((backup / 'game-a/applied-provenance.json').read_bytes(), applied)
        city.verify_client(self.root, city.CLIENTS[0])
        self.assertEqual(city.refresh_settings(self.root)['status'], 'settings_unchanged')
        city.rollback(self.root)
        self.assertEqual(target.read_bytes(), preferences)
        restored = city.verify_client(self.root, city.CLIENTS[0])
        self.assertNotIn(city.OVERLAY_KEY, restored)
        row = next(row for row in restored['files'] if row['path'] == 'base/config.cfg')
        self.assertEqual(row['sha256'], sha(preferences))
        self.assertEqual((self.client() / 'silver.dll').read_bytes(), self.resources['silver.dll'])

    def test_unsafe_endpoint_or_console_command_is_never_reconciled(self):
        city.prepare(self.root)
        proof = (self.client() / PROOF).read_bytes()
        config = self.client() / 'base/config.cfg'
        for data in (SETTINGS.replace(b'127.0.0.1', b'185.184.42.88'),
                     SETTINGS + b'exec unexpected.cfg\r\n',
                     SETTINGS + b'orange_port 28512\r\n',
                     SETTINGS + b'r_vsync 1;exec unexpected.cfg\r\n'):
            with self.subTest(case=sha(data)):
                config.write_bytes(data)
                with self.assertRaises(ValueError):
                    city.refresh_settings(self.root)
                self.assertEqual(config.read_bytes(), data)
                self.assertEqual((self.client() / PROOF).read_bytes(), proof)

    def test_config_change_never_hides_an_unrelated_native_change(self):
        city.prepare(self.root)
        target = self.client() / 'base/config.cfg'
        preferences = SETTINGS.replace(b'r_width 1024', b'r_width 1600')
        target.write_bytes(preferences)
        (self.client('b') / 'orange.dll').write_bytes(b'changed native module')
        first = (self.client() / PROOF).read_bytes()
        with self.assertRaisesRegex(ValueError, 'resource changed'):
            city.refresh_settings(self.root)
        self.assertEqual((self.client() / PROOF).read_bytes(), first)
        self.assertEqual(target.read_bytes(), preferences)

    def test_rollback_refuses_unaccepted_change_after_settings_reconciliation(self):
        city.prepare(self.root)
        target = self.client() / 'base/config.cfg'
        target.write_bytes(SETTINGS.replace(b'r_width 1024', b'r_width 1600'))
        city.refresh_settings(self.root)
        target.write_bytes(SETTINGS.replace(b'r_width 1024', b'r_width 1920'))
        first = digest(self.client() / 'silver.dll')
        with self.assertRaisesRegex(ValueError, 'Reconciled settings changed'):
            city.rollback(self.root)
        self.assertEqual(digest(self.client() / 'silver.dll'), first)

    def test_launcher_uses_guarded_native_multi_after_settings_verification(self):
        city.prepare(self.root)
        helper = self.root / 'reports/contracts-local/clients/bin/TioContractsQaClient.exe'
        helper.parent.mkdir(parents=True)
        helper.write_bytes(b'fixture helper')
        result = city.install_launchers(self.root)
        self.assertEqual(result['graphical_clients_started'], 0)
        for relative in city.CLIENTS:
            path = self.root / relative / 'launch-client.ps1'
            self.assertTrue(path.read_bytes().startswith(b'\xef\xbb\xbf'))
            script = path.read_text(encoding='utf-8-sig')
            self.assertIn('--refresh-settings', script)
            self.assertIn("Write-Host 'Проверяю файлы", script)
            self.assertLess(script.index("Write-Host 'Проверяю файлы"), script.index('--refresh-settings'))
            self.assertIn('& $helper start $clientRoot --native-multi', script)
            self.assertNotIn('Start-Process', script)
            self.assertLess(script.index('--refresh-settings'), script.index('& $helper start'))

    def test_full_observed_native_save_schema_reconciles_and_rolls_back(self):
        city.prepare(self.root)
        fixture = city.ROOT / 'reports/contracts-local/city-ui/qa-loader/fixtures/native-save-sanitized.cfg'
        native = fixture.read_bytes().replace(b'name ""', 'name "Тестовый боец"'.encode('cp1251')).replace(
            b'r_device_name ""', 'r_device_name "Тестовый адаптер"'.encode('cp1251'))
        target = self.client() / 'base/config.cfg'
        target.write_bytes(native)
        # The original client also supports an endpoint-only autoexec.
        autoexec = self.client() / 'base/autoexec.cfg'
        autoexec.write_bytes(b'orange_addr "127.0.0.1"\r\norange_port "28512"\r\n')
        names = city.validate_settings(native)
        self.assertEqual(len(names), 116)
        self.assertIn('last_user_agreement_hash', names)
        self.assertIn('cl_lastpass', names)
        self.assertIsInstance(names, set)  # No identity values returned.
        city.refresh_settings(self.root)
        city.verify_client(self.root, city.CLIENTS[0])
        city.rollback(self.root)
        self.assertEqual(target.read_bytes(), native)
        self.assertEqual(autoexec.read_bytes(), b'orange_addr "127.0.0.1"\r\norange_port "28512"\r\n')

    def test_real_native_preference_ranges_and_remembered_strings_are_bounded(self):
        for suffix in (b'volume 101\r\n', b'r_monitor 9999\r\n', b'last_user_agreement_hash 4294967296\r\n',
                       b'name "bad;exec hostile.cfg"\r\n', b'r_gamma 1.0\r\n'):
            with self.subTest(case=sha(suffix)), self.assertRaises(ValueError):
                city.validate_settings(SETTINGS + suffix)

    def test_invocation_digest_cache_reuses_only_same_stable_physical_file(self):
        source = self.source / 'base/gui/unchanged.png'
        alias = self.client() / 'base/gui/unchanged.png'
        cache = city.InvocationDigests()
        self.assertEqual(cache(source), digest(source))
        self.assertEqual(cache(alias), digest(alias))
        self.assertEqual(cache.hash_reads, 1)
        self.assertEqual(cache.cache_hits, 1)
        # A new invocation always reads the bytes again.
        fresh = city.InvocationDigests()
        self.assertEqual(fresh(alias), digest(alias))
        self.assertEqual(fresh.hash_reads, 1)

    def test_invocation_cache_detects_same_size_write_even_when_mtime_restored(self):
        source = self.source / 'base/gui/unchanged.png'
        cache = city.InvocationDigests()
        before = source.stat()
        old = cache(source)
        source.write_bytes(b'X' * before.st_size)
        os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertNotEqual(cache(source), old)
        self.assertEqual(cache.hash_reads, 2)

    def test_invocation_cache_detects_atomic_detachment_and_private_replacement(self):
        target = self.client() / 'base/gui/unchanged.png'
        source = self.source / 'base/gui/unchanged.png'
        cache = city.InvocationDigests()
        initial = cache(source)
        city.atomic(target, data=b'X' * target.stat().st_size)
        self.assertNotEqual(cache(target), initial)
        self.assertEqual(cache(source), initial)
        # Removing a hardlink may also advance the source's native ChangeTime;
        # a harmless extra read is allowed, while detached bytes cannot reuse it.
        self.assertGreaterEqual(cache.hash_reads, 2)

    def test_invocation_cache_falls_back_when_filesystem_has_no_safe_identity(self):
        source = self.source / 'base/gui/unchanged.png'
        cache = city.InvocationDigests()
        with patch.object(city.InvocationDigests, '_fingerprint', return_value=None):
            self.assertEqual(cache(source), digest(source))
            self.assertEqual(cache(source), digest(source))
        self.assertEqual(cache.hash_reads, 2)
        self.assertEqual(cache.cache_hits, 0)

    def test_invocation_cache_refuses_content_changes_during_one_read(self):
        source = self.source / 'base/gui/unchanged.png'
        cache = city.InvocationDigests()
        with patch.object(city.InvocationDigests, '_fingerprint', side_effect=[('before',), ('changed',)]):
            with self.assertRaisesRegex(ValueError, 'changed during hash verification'):
                cache(source)

    def test_native_empty_identity_and_unquoted_gpu_fields_are_accepted(self):
        data = SETTINGS + ('cl_lastlogin\r\ncl_lastpass \r\nr_device_name Synthetic GPU Adapter\r\n'
                           'name Тестовый боец\r\n').encode('cp1251')
        names = city.validate_settings(data)
        self.assertTrue({'cl_lastlogin', 'cl_lastpass', 'r_device_name', 'name'} <= names)
        self.assertIsInstance(names, set)

    def test_native_unquoted_opaque_reconciliation_preserves_saved_bytes(self):
        city.prepare(self.root)
        target = self.client() / 'base/config.cfg'
        saved = SETTINGS + b'cl_lastlogin\r\ncl_lastpass\r\nr_device_name Synthetic GPU Adapter\r\n'
        target.write_bytes(saved)
        city.refresh_settings(self.root)
        city.verify_client(self.root, city.CLIENTS[0])
        city.rollback(self.root)
        self.assertEqual(target.read_bytes(), saved)

    def test_native_opaque_fallback_does_not_accept_other_fields_or_commands(self):
        for suffix in (b'volume\r\n', b'volume 50 extra\r\n', b'unknown\r\n', b'g_language russian extra\r\n',
                       b'r_device_name Generic;exec evil.cfg\r\n', b'r_device_name exec evil.cfg\r\n',
                       b'r_device_name script evil.cfg\r\n', b'r_device_name Generic "Adapter\r\n',
                       b"r_device_name Generic 'Adapter\r\n", b'cl_lastpass\r\ncl_lastpass\r\n'):
            with self.subTest(case=sha(suffix)), self.assertRaises(ValueError):
                city.validate_settings(SETTINGS + suffix)
        for control in (0, 7, 11, 12, 31, 127):
            with self.subTest(control=control), self.assertRaises(ValueError):
                city.validate_settings(SETTINGS + b'r_device_name GPU' + bytes([control]) + b'\r\n')
        for endpoint in (b'orange_addr\r\n', b'orange_addr 127.0.0.1 extra\r\n', b'orange_addr 185.184.42.88\r\n'):
            replaced = SETTINGS.replace(b'orange_addr 127.0.0.1\r\n', endpoint)
            with self.subTest(case=sha(endpoint)), self.assertRaises(ValueError):
                city.validate_settings(replaced)


if __name__ == '__main__':
    unittest.main()
