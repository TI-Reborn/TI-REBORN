"""UI releases must preserve gameplay records and reject unsafe/stale packages."""
import copy
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from launcher.build_menu_interface_update import build
from tools.deploy_menu_interface_remote import (read_release, sha, unpack_release,
                                               validate_binary_patch, validate_manifests,
                                               validate_ui_path)


def record(name, raw, seed=False):
    return dict(path=name, size=len(raw), sha256=sha(raw), seed=seed)


class MenuInterfaceReleaseTests(unittest.TestCase):
    def setUp(self):
        self.previous = dict(schema=1, version='2026.10.07.3', news='Existing news', files=[
            record('base/pda/mainbg.jpg', b'old background'),
            record('base/gui/frame.tga', b'old frame'),
            record('base/config.cfg', b'personal config', seed=True),
            record('silver.dll', b'current executable'),
            record('base/models/armor.mdjx', b'current geometry'),
        ])
        self.updated = copy.deepcopy(self.previous)
        self.updated['version'] = '2026.10.07.4'
        self.updated['files'][0].update(size=14, sha256=sha(b'new background'))
        self.allowed = ['base/pda/mainbg.jpg']

    def check_rejected(self, mutate, message):
        new = copy.deepcopy(self.updated)
        mutate(new)
        with self.assertRaisesRegex(ValueError, message):
            validate_manifests(self.previous, new, self.allowed)

    def test_valid_release_preserves_non_ui_records(self):
        self.updated['news'] = 'New menu\n\nExisting news'
        before, after, allowed = validate_manifests(self.previous, self.updated, self.allowed)
        self.assertEqual(allowed, set(self.allowed))
        for name in ('silver.dll', 'base/config.cfg', 'base/models/armor.mdjx'):
            self.assertEqual(before[name], after[name])

    def test_builder_removes_stale_archive_for_file_updates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.previous['archive'] = dict(size=100, sha256='a'*64, filesSha256='b'*64)
            previous = root/'previous.json'
            previous.write_text(json.dumps(self.previous))
            assets = root/'assets'; assets.mkdir()
            (assets/'frame.tga').write_bytes(b'new frame')
            output = root/'release'
            build(previous, assets, {'base/gui/frame.tga':'frame.tga'}, '2026.10.07.4', output)
            _, raw, _, _, _ = read_release(output/'client-release')
            self.assertNotIn('archive', json.loads(raw))
            self.assertEqual(json.loads((output/'client-release/previous-manifest.json').read_bytes()), self.previous)

    def test_ui_release_cannot_inject_or_modify_archive(self):
        self.updated['archive'] = dict(size=100, sha256='a'*64, filesSha256='b'*64)
        with self.assertRaisesRegex(ValueError, 'Unapproved client archive'):
            validate_manifests(self.previous, self.updated, self.allowed)
        self.previous['archive'] = dict(size=100, sha256='c'*64, filesSha256='b'*64)
        with self.assertRaisesRegex(ValueError, 'Unapproved client archive'):
            validate_manifests(self.previous, self.updated, self.allowed)

    def test_existing_empty_non_ui_file_is_preserved(self):
        self.previous['files'].append(record('base/SalesInfo.txt', b''))
        self.updated['files'].append(record('base/SalesInfo.txt', b''))
        before, after, _ = validate_manifests(self.previous, self.updated, self.allowed)
        self.assertEqual(before['base/SalesInfo.txt'], after['base/SalesInfo.txt'])

    def test_absent_optional_seed_flag_is_preserved(self):
        self.previous['files'][4].pop('seed')
        self.updated['files'][4].pop('seed')
        before, after, _ = validate_manifests(self.previous, self.updated, self.allowed)
        self.assertNotIn('seed', after['base/models/armor.mdjx'])
        self.assertEqual(before['base/models/armor.mdjx'], after['base/models/armor.mdjx'])

    def test_rejects_non_ui_and_traversal_paths(self):
        for name in ('silver.dll', 'base/config.cfg', 'data/reservation.sqlite3',
                     'base/pda/../config.cfg', 'base/pda/a/../../gui/frame.png',
                     'base/pda\\frame.png', '/base/pda/mainbg.jpg',
                     'base/pda/C:frame.png', 'base/pda/a.png ', 'base/pda/log.txt'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_ui_path(name)

    def test_personal_gui_hd_navigation_paths_are_exact_and_density_matched(self):
        for density in (100, 125, 150, 200):
            for symbol in ('map', 'soldier', 'ratings', 'money', 'filter', 'handshake', 'info', 'mail',
                           'refresh', 'rifle', 'search', 'squad', 'wrench', 'zoom-minus', 'zoom-plus'):
                validate_ui_path(f'base/ui-hd/icons/a/{density}/a-{symbol}-{density}.png')
        validate_ui_path('base/ui-hd/battle-controls/hd4-bui-plates.png')
        for name in ('base/ui-hd/icons/a/100/a-map-200.png',
                     'base/ui-hd/icons/a/300/a-map-300.png',
                     'base/ui-hd/icons/a/100/a-map-100.dll',
                     'base/ui-hd/icons/a/100/a-inventory-100.png',
                     'base/ui-hd/battle-controls/hd4-bui-glyphs.png',
                     'base/ui-hd/battle-controls/other-plates.png',
                     'base/ui-hd/icons/a/100/../../config.cfg'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_ui_path(name)

    def test_only_exact_menu_font_metrics_and_atlas_are_allowed(self):
        for name in ('base/fonts/menu.xml', 'base/fonts/menu.png'):
            validate_ui_path(name)
        for name in ('base/fonts/fonts.xml', 'base/fonts/nice.png', 'base/fonts/Menu.xml',
                     'base/fonts/menu2.xml', 'base/fonts/menu.xml.bak',
                     'base/pda/settings.xml', 'base/shared config/items.xml',
                     'base/fonts/../pda/menuframe.png'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_ui_path(name)

    def test_rejects_changed_gameplay_binary(self):
        self.check_rejected(lambda new: new['files'][3].update(sha256=sha(b'changed executable')),
                            'Changed records differ')

    def test_rejects_added_file(self):
        self.check_rejected(lambda new: new['files'].append(record('base/gui/new.png', b'new')),
                            'Manifest paths or ordering changed')

    def test_exact_new_menu_button_requires_explicit_addition_list(self):
        new = copy.deepcopy(self.updated)
        new['files'].append(record('base/pda/menubutton.png', b'button atlas'))
        allowed = self.allowed + ['base/pda/menubutton.png']
        with self.assertRaisesRegex(ValueError, 'Manifest paths or ordering changed'):
            validate_manifests(self.previous, new, allowed)
        before, after, _ = validate_manifests(self.previous, new, allowed,
                                             added_paths=['base/pda/menubutton.png'])
        self.assertEqual(list(after), list(before) + ['base/pda/menubutton.png'])
        invalid = copy.deepcopy(new)
        invalid['files'][-1]['path'] = 'base/gui/other.png'
        with self.assertRaisesRegex(ValueError, 'Unapproved UI resource addition'):
            validate_manifests(self.previous, invalid, self.allowed + ['base/gui/other.png'],
                               added_paths=['base/gui/other.png'])

    def test_builder_packages_explicit_new_button_without_changing_existing_records(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            previous = root / 'previous.json'
            previous.write_text(json.dumps(self.previous))
            assets = root / 'assets'
            assets.mkdir()
            (assets / 'menubutton.png').write_bytes(b'new button atlas')
            output = root / 'release'
            proof = build(previous, assets, {'base/pda/menubutton.png': 'menubutton.png'},
                          '2026.10.07.4', output, added_paths=['base/pda/menubutton.png'])
            self.assertEqual(proof['unchanged_files'], len(self.previous['files']))
            self.assertEqual(proof['added_paths'], ['base/pda/menubutton.png'])
            old, new, before, after, allowed = read_release(output / 'client-release')
            self.assertEqual(json.loads(new)['files'][:-1], self.previous['files'])
            self.assertEqual(allowed, {'base/pda/menubutton.png'})

    def test_both_exact_new_menu_atlases_require_explicit_additions_and_append_sorted(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            previous = root / 'previous.json'
            previous.write_text(json.dumps(self.previous))
            assets = root / 'assets'
            assets.mkdir()
            (assets / 'menubutton.png').write_bytes(b'new button atlas')
            (assets / 'menuframe.png').write_bytes(b'new main menu frame atlas')
            additions = ['base/pda/menuframe.png', 'base/pda/menubutton.png']
            overrides = {name: Path(name).name for name in additions}
            output = root / 'release'
            proof = build(previous, assets, overrides, '2026.10.07.4', output,
                          added_paths=additions)
            self.assertEqual(proof['unchanged_files'], len(self.previous['files']))
            self.assertEqual(proof['added_paths'], sorted(additions))
            _, new_raw, before, after, allowed = read_release(output / 'client-release')
            self.assertEqual(json.loads(new_raw)['files'][:-2], self.previous['files'])
            self.assertEqual(list(after), list(before) + sorted(additions))
            self.assertEqual(allowed, set(additions))
            with self.assertRaises(ValueError):
                build(previous, assets, overrides, '2026.10.07.4', root / 'refused',
                      added_paths=['base/pda/menubutton.png'])

    def test_exact_menu_font_additions_are_non_seed_and_preserve_existing_records(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            previous = root / 'previous.json'
            previous.write_text(json.dumps(self.previous))
            assets = root / 'assets'
            assets.mkdir()
            (assets / 'menu.xml').write_bytes(b'<font><glyph code="65" /></font>')
            (assets / 'menu.png').write_bytes(b'new menu font atlas')
            additions = ['base/fonts/menu.xml', 'base/fonts/menu.png']
            overrides = {name: Path(name).name for name in additions}
            output = root / 'release'
            proof = build(previous, assets, overrides, '2026.10.07.4', output,
                          added_paths=additions)
            self.assertEqual(proof['unchanged_files'], len(self.previous['files']))
            _, new_raw, before, after, allowed = read_release(output / 'client-release')
            self.assertEqual(json.loads(new_raw)['files'][:-2], self.previous['files'])
            self.assertEqual(list(after), list(before) + sorted(additions))
            self.assertEqual(allowed, set(additions))
            self.assertTrue(all(after[name]['seed'] is False for name in additions))
            for name in additions:
                invalid = json.loads(new_raw)
                next(item for item in invalid['files'] if item['path'] == name)['seed'] = True
                with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'New UI resource metadata is invalid'):
                    validate_manifests(self.previous, invalid, sorted(additions),
                                       added_paths=additions)

    def test_rejects_removed_file(self):
        self.check_rejected(lambda new: new['files'].pop(), 'Manifest paths or ordering changed')

    def test_rejects_duplicate_record(self):
        self.check_rejected(lambda new: new['files'].append(new['files'][0]),
                            'Duplicate manifest path')

    def test_rejects_reordering(self):
        self.check_rejected(lambda new: new['files'].reverse(), 'Manifest paths or ordering changed')

    def test_rejects_seed_override(self):
        old = copy.deepcopy(self.previous)
        old['files'][0]['seed'] = True
        new = copy.deepcopy(self.updated)
        new['files'][0]['seed'] = True
        with self.assertRaisesRegex(ValueError, 'Seed settings cannot be replaced'):
            validate_manifests(old, new, self.allowed)

    def test_rejects_record_metadata_change(self):
        self.check_rejected(lambda new: new['files'][0].update(seed=True),
                            'Seed settings cannot be replaced')
        self.check_rejected(lambda new: new['files'][0].update(optional='unexpected'),
                            'Non-content file metadata changed')

    def test_rejects_manifest_metadata_change(self):
        self.check_rejected(lambda new: new.update(download_url='https://other.invalid'),
                            'Non-release manifest metadata changed')

    def test_rejects_stale_versions(self):
        for version in ('2026.10.07.3', '2026.10.06.99'):
            with self.subTest(version=version):
                self.check_rejected(lambda new: new.update(version=version), 'Client version must increase')

    def binary_fixture(self, updated_raw=b'Current executable'):
        old_raw = b'current executable'
        new = copy.deepcopy(self.previous)
        new['version'] = '2026.10.07.4'
        new['files'][3] = record('silver.dll', updated_raw)
        plan = dict(path='silver.dll', previous_sha256=sha(old_raw),
                    updated_sha256=sha(updated_raw), changes=[
                        dict(offset=0, previous_hex='63', updated_hex='43')])
        return old_raw, updated_raw, new, plan

    def test_binary_patch_requires_plan_and_matches_exact_old_and_new_bytes(self):
        old_raw, new_raw, new, plan = self.binary_fixture()
        with self.assertRaisesRegex(ValueError, 'requires an explicit patch plan'):
            validate_manifests(self.previous, new, ['silver.dll'])
        before, after, _ = validate_manifests(self.previous, new, ['silver.dll'], plan)
        validate_binary_patch(old_raw, new_raw, plan, before['silver.dll'], after['silver.dll'])
        self.assertEqual(before['base/config.cfg'], after['base/config.cfg'])

    def test_binary_patch_rejects_unlisted_changes_and_mismatched_previous_blob(self):
        old_raw, new_raw, new, plan = self.binary_fixture(b'Current Executable')
        before, after, _ = validate_manifests(self.previous, new, ['silver.dll'], plan)
        with self.assertRaisesRegex(ValueError, 'outside the explicit UI patch ranges'):
            validate_binary_patch(old_raw, new_raw, plan, before['silver.dll'], after['silver.dll'])
        with self.assertRaisesRegex(ValueError, 'blob size/checksum mismatch'):
            validate_binary_patch(b'different old blob', new_raw, plan,
                                  before['silver.dll'], after['silver.dll'])

    def test_binary_patch_rejects_overlap_wrong_hash_wrong_bytes_and_file_growth(self):
        old_raw, new_raw, new, plan = self.binary_fixture()
        for mutate, message in (
                (lambda p: p.update(previous_sha256='0' * 64), 'hashes differ'),
                (lambda p: p['changes'].append(p['changes'][0]), 'overlap or are unordered'),
                (lambda p: p['changes'][0].update(previous_hex='00'), 'bytes differ'),
                (lambda p: p['changes'][0].update(offset=len(old_raw)), 'exceeds file size')):
            invalid = copy.deepcopy(plan)
            mutate(invalid)
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                before, after, _ = validate_manifests(self.previous, new, ['silver.dll'], invalid)
                validate_binary_patch(old_raw, new_raw, invalid, before['silver.dll'], after['silver.dll'])
        grown = copy.deepcopy(new)
        grown['files'][3]['size'] += 1
        with self.assertRaisesRegex(ValueError, 'cannot change the file size'):
            validate_manifests(self.previous, grown, ['silver.dll'], plan)

    def test_binary_builder_carries_verified_prior_blob_and_plan(self):
        old_raw, new_raw, new, plan = self.binary_fixture()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            previous = root / 'previous.json'
            previous.write_text(json.dumps(self.previous))
            assets = root / 'assets'
            assets.mkdir()
            (assets / 'silver.dll').write_bytes(new_raw)
            prior_binary = root / 'prior-silver.dll'
            prior_binary.write_bytes(old_raw)
            output = root / 'release'
            proof = build(previous, assets, {'silver.dll': 'silver.dll'}, '2026.10.07.4',
                          output, patch_plan=plan, previous_binary=prior_binary)
            self.assertTrue(proof['validated_binary_patch'])
            stage = root / 'stage'
            stage.mkdir()
            unpack_release(output / 'patch.tar.gz', proof['archive_sha256'], stage)
            self.assertEqual((stage / 'previous-blobs' / sha(old_raw)).read_bytes(), old_raw)
            self.assertEqual(json.loads((stage / 'patch-plan.json').read_bytes()), plan)

    def test_rejects_extra_missing_and_duplicate_allowlist_entries(self):
        for allowed in ([], self.allowed * 2, self.allowed + ['base/gui/frame.tga'],
                        ['base/gui/missing.png']):
            with self.subTest(allowed=allowed), self.assertRaises(ValueError):
                validate_manifests(self.previous, self.updated, allowed)

    def test_builder_archive_roundtrip_and_checksum(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            previous = root / 'previous.json'
            previous.write_text(json.dumps(self.previous))
            assets = root / 'assets'
            assets.mkdir()
            (assets / 'mainbg.jpg').write_bytes(b'new background')
            output = root / 'release'
            proof = build(previous, assets, {'base/pda/mainbg.jpg': 'mainbg.jpg'},
                          '2026.10.07.4', output)
            self.assertEqual(proof['changed_files'], 1)
            self.assertEqual(proof['unchanged_files'], 4)
            stage = root / 'stage'
            stage.mkdir()
            old, new, before, after, allowed = unpack_release(output / 'patch.tar.gz',
                                                            proof['archive_sha256'], stage)
            self.assertEqual(old, previous.read_bytes())
            self.assertEqual(json.loads(new)['version'], '2026.10.07.4')
            self.assertEqual(after['silver.dll'], before['silver.dll'])
            with self.assertRaisesRegex(ValueError, 'archive checksum mismatch'):
                unpack_release(output / 'patch.tar.gz', '0' * 64, stage)
            (stage / 'blobs' / after[self.allowed[0]]['sha256']).write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError, 'blob size/checksum mismatch'):
                read_release(stage)

    def test_builder_rejects_escape_and_empty_payload_before_writing_release(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            previous = root / 'previous.json'
            previous.write_text(json.dumps(self.previous))
            assets = root / 'assets'
            assets.mkdir()
            (assets / 'empty.jpg').write_bytes(b'')
            (root / 'outside.jpg').write_bytes(b'outside')
            for asset in ('../outside.jpg', str(root / 'outside.jpg'), 'empty.jpg'):
                with self.subTest(asset=asset), self.assertRaises(ValueError):
                    build(previous, assets, {'base/pda/mainbg.jpg': asset},
                          '2026.10.07.4', root / 'refused-release')
                self.assertFalse((root / 'refused-release').exists())

    def test_archive_rejects_symlinks_traversal_and_duplicate_members(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for mode in ('symlink', 'traversal', 'duplicate'):
                archive = root / (mode + '.tar.gz')
                with tarfile.open(archive, 'w:gz') as bundle:
                    member = tarfile.TarInfo('manifest.json' if mode != 'traversal' else '../escape')
                    if mode == 'symlink':
                        member.type = tarfile.SYMTYPE
                        member.linkname = '/etc/tio-server/server.toml'
                        bundle.addfile(member)
                    else:
                        member.size = 2
                        bundle.addfile(member, io.BytesIO(b'{}'))
                        if mode == 'duplicate':
                            bundle.addfile(member, io.BytesIO(b'{}'))
                stage = root / (mode + '-stage')
                stage.mkdir()
                with self.subTest(mode=mode), self.assertRaises(ValueError):
                    unpack_release(archive, sha(archive.read_bytes()), stage)
                self.assertEqual(list(stage.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
