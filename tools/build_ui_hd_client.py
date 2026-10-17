"""Build the selected classic icons + Roboto font client from pinned release12.

Pure native composition and preservation checks. This never modifies an
installed game, configuration, hosted account or public update manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import pefile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BASE_SHA = '87645b946317a645552c3c2a5fcf586784d3920548288e2312dfb9ace065df4d'
TI_SHA = 'e288de090e162660604750075c3e633f60744ee8a24915a9bc24e8cc39ee3f1c'
BASE = ROOT / 'reports/ui-modernization/graphical/source' / BASE_SHA / 'silver.dll'
OUT = ROOT / 'reports/ui-hd-assets/client'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(value, message):
    if not value:
        raise ValueError(message)


def safe_output(path):
    path = Path(path).absolute()
    scope = (ROOT / 'reports/ui-hd-assets').absolute()
    require(path.is_relative_to(scope), 'Output escaped the HD report folder')
    for part in (path, *path.parents):
        require(not part.is_symlink() and not part.is_junction(), 'Output uses a filesystem link')
        if part == ROOT.absolute():
            break
    require(path.resolve() == path, 'Resolved output differs from its approved path')
    return path


def reconstruct(source=None):
    from deploy import client_ui_hd_fonts as fonts
    from deploy import client_ui_hd_icons as icons
    source = BASE.read_bytes() if source is None else source
    require(sha(source) == BASE_SHA, 'Expected exact public12 native source')
    intermediate = fonts.patch(source, expected_sha=BASE_SHA)
    final = icons.patch(intermediate, expected_sha=sha(intermediate))
    return final, intermediate


def preserve(source, final):
    from tools.hosted_graphical_qa_bridge import SPANS
    before, after = pefile.PE(data=source), pefile.PE(data=final)
    checks = []
    try:
        for name, rva, size in (
            ('Screen Apply runtime', 0x823000, 0x2000),
            ('UI scale runtime and input', 0x825000, 0x4000),
            ('UI scale controls', 0x829000, 0x2000),
            ('Portrait512 runtime', 0x82b000, 0x3000),
        ):
            old, new = before.get_data(rva, size), after.get_data(rva, size)
            require(len(old) == size and old == new, name + ' was changed')
            checks.append({'name': name, 'rva': hex(rva), 'bytes': size,
                           'sha256': sha(old), 'byte_identical': True})
        for name, va, size, expected in SPANS:
            require(sha(after.get_data(va - 0x400000, size)) == expected,
                    'Native authentication function changed: ' + name)
        require(before.FILE_HEADER.NumberOfSections == after.FILE_HEADER.NumberOfSections,
                'Unexpected native PE section header addition')
        for section in after.sections:
            require(section.PointerToRawData + section.SizeOfRawData <= len(final),
                    'PE section exceeds candidate bytes')
        return {'prior_runtime': checks, 'native_authentication_spans': len(SPANS),
                'section_count': after.FILE_HEADER.NumberOfSections,
                'size_of_image': hex(after.OPTIONAL_HEADER.SizeOfImage)}
    finally:
        before.close()
        after.close()


def build(output=OUT):
    output = safe_output(output)
    source = BASE.read_bytes()
    final, intermediate = reconstruct(source)
    checks = preserve(source, final)
    repeated, _ = reconstruct(source)
    require(repeated == final, 'Native composition is not deterministic')
    ti = (ROOT / 'reports/ui-modernization/baseline/ti.exe').read_bytes()
    require(sha(ti) == TI_SHA, 'Launcher-pinned executable differs')
    output.mkdir(parents=True, exist_ok=True)
    safe_output(output / 'silver.dll').write_bytes(final)
    safe_output(output / 'fonts-only.dll').write_bytes(intermediate)
    proof = {'result': 'PASS', 'selected_icons': 'A Classic HD',
             'selected_font': 'B Roboto Condensed', 'base_sha256': BASE_SHA,
             'candidate_sha256': sha(final), 'candidate_bytes': len(final),
             'fonts_candidate_sha256': sha(intermediate), 'ti_sha256': TI_SHA,
             'ti_changed': False, 'deterministic': True,
             'graphical_client_validation': False, 'published': False,
             **checks}
    safe_output(output / 'build-proof.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2),
                                           encoding='utf-8')
    return proof


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=OUT)
    args = parser.parse_args()
    print(json.dumps(build(args.output), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
