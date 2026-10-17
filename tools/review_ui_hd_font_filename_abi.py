"""Inspect real embedded font filenames through the pinned TI basename scanner.

This is offline x86 evidence. It opens no game, GPU, network, OS file loader or
hosted database. Only Unicode substring allocation is a fixture boundary; the
real TI ExtractFileName, delimiter scanner and length reads execute unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from deploy import client_ui_hd_fonts as fonts
from tools.verify_ui_hd_icons_native import NativeLoaderFixture, DATA, get, put


def digest(data):
    return hashlib.sha256(data).hexdigest()


def terminated_utf16(u, address):
    raw = bytearray()
    for index in range(256):
        word = bytes(u.mem_read(address + index * 2, 2))
        if word == b'\0\0':
            return raw.decode('utf-16le')
        raw.extend(word)
    raise ValueError('Embedded native filename exceeds its explicit bound')


def review(candidate, expected):
    raw = Path(candidate).read_bytes()
    if digest(raw) != expected:
        raise ValueError('Candidate is not the exact independently reviewed SHA')
    ti_path = ROOT / 'reports/ui-modernization/baseline/ti.exe'
    ti = ti_path.read_bytes()
    if digest(ti) != fonts.TI_SHA:
        raise ValueError('Pinned native TI differs')
    manifest = fonts.assets_manifest()
    rows = []
    for base in (0x10000000, 0x14000000):
        fixture = NativeLoaderFixture(raw, ti, base, 0x400000)
        out = DATA + 0xd000
        entry = 0x400000 + 0x424d7c - base
        for index, role in enumerate(manifest['fonts']):
            for density, atlas in enumerate(role['density_sets']):
                pointer = get(fixture.u, base + fonts.TABLE + index * 0x80
                              + 0x38 + density * 4) + base + 12
                text = terminated_utf16(fixture.u, pointer)
                length = get(fixture.u, pointer - 4)
                if text.replace('\\', '/') != atlas['path']:
                    raise ValueError('Embedded font filename differs from selected resource')
                fixture.run(entry, eax=pointer, edx=out)
                actual = fixture.text(get(fixture.u, out))
                # A diagnostic counterfactual changes only this ephemeral
                # Unicorn header. No candidate or installed file is written.
                put(fixture.u, pointer - 4, len(text))
                fixture.run(entry, eax=pointer, edx=out)
                corrected = fixture.text(get(fixture.u, out))
                put(fixture.u, pointer - 4, length)
                expected_name = atlas['path'].split('/')[-1]
                if corrected != expected_name:
                    raise ValueError('Actual native scanner did not reproduce the approved basename')
                rows.append(dict(silver_base=hex(base), font=role['font'],
                                 density=fonts.PERCENTS[density], path=text,
                                 header_length=length, character_count=len(text),
                                 actual_native_basename=actual,
                                 expected_native_basename=expected_name,
                                 character_count_header_native_basename=corrected,
                                 actual_matches=actual == expected_name and length == len(text)))
        if not {'0x424d7c', '0x42f698', '0x42f7e4'} <= fixture.loader_executed:
            raise ValueError('Native basename extraction did not execute')
    passed = all(row['actual_matches'] for row in rows)
    return dict(result='PASS' if passed else 'FAIL_CANDIDATE_NATIVE_FILENAME_ABI',
                candidate_sha256=expected, candidate_bytes=len(raw),
                native_ti_sha256=fonts.TI_SHA,
                font_manifest_sha256=fonts.ASSET_MANIFEST_SHA,
                checks=len(rows), native_code=['TI424d7c', 'TI42f698', 'TI42f7e4'],
                native_unicode_length_semantics='UTF16 character count at pointer-4',
                actual_unique_keys_per_base=len({row['actual_native_basename'] for row in rows}),
                corrected_unique_keys_per_base=len({row['expected_native_basename'] for row in rows}),
                all_corrected_keys_match=True, rows=rows,
                external_boundary=['Unicode substring allocation'],
                graphically_validated=False, installed_client_modified=False,
                network_calls=0, remote_mutations=0, publish_allowed=False,
                reviewer_sha256=digest(Path(__file__).read_bytes()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--candidate-sha256', required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    report = args.report.absolute()
    scope = ROOT / 'reports/ui-hd-assets/deployment'
    if not report.is_relative_to(scope) or report.exists():
        raise ValueError('Use a new independent deployment evidence path')
    for parent in (report, *report.parents):
        if parent.is_symlink() or parent.is_junction():
            raise ValueError('Evidence path contains a filesystem link')
        if parent == ROOT:
            break
    if report.resolve() != report:
        raise ValueError('Resolved evidence path differs')
    result = review(args.candidate, args.candidate_sha256)
    report.parent.mkdir(parents=True, exist_ok=True)
    with report.open('x', encoding='utf-8') as output:
        json.dump(result, output, ensure_ascii=True, indent=2)
        output.write('\n')
    print(json.dumps({key: result[key] for key in ('result', 'checks', 'candidate_sha256',
                         'actual_unique_keys_per_base', 'corrected_unique_keys_per_base')}))


if __name__ == '__main__':
    main()
