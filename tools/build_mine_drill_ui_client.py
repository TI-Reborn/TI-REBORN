"""Compose mine hit testing and native icon API repairs from trusted .1 bytes."""
import hashlib
import json
from pathlib import Path
import sys

import pefile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from deploy import client_battle_ui_hd as icons
from deploy import client_mine_hover_scale as hover
from tools import publish_mine_drill_ui_remote as publisher


def sha(data):
    return hashlib.sha256(data).hexdigest()


def build():
    source = publisher.BASELINE.parent.joinpath('silver.dll').read_bytes()
    if (sha(source), len(source)) != (publisher.SILVER_SHA, publisher.SILVER_BYTES):
        raise ValueError('Expected actual trusted .1 baseline')
    folder = publisher.REPORT_ROOT / 'client'
    qa = publisher.REPORT_ROOT / 'composition'
    if folder.exists() or qa.exists():
        raise ValueError('Preserve previous build evidence')
    icon_fixed = icons.repair_published(source, expected_sha=sha(source))
    if sha(icon_fixed) != 'bb04c65d4b24df44bfc91b0eb4e8fa799f369c037778797739ed78a70bbc3684':
        raise ValueError('Icon repair differs from reviewed native baseline comparison')
    candidate = hover.patch(icon_fixed, expected_sha=sha(icon_fixed))
    hover_only = hover.patch(source, expected_sha=sha(source))
    if icons.repair_published(hover_only, expected_sha=sha(hover_only)) != candidate:
        raise ValueError('Repairs do not commute')
    pe = pefile.PE(data=source)
    spans = sorted([
        (pe.get_offset_from_rva(icons.BASE_RVA), 0xc00,
         'Repair original draw API frame/color argument order and color conversion'),
        (pe.get_offset_from_rva(hover.HOOK - hover.IMAGE_BASE), 5,
         'Detect hovered mine occurrence using physical cursor in world coordinates'),
        (pe.get_offset_from_rva(hover.SLOT_RVA), hover.SLOT_SIZE,
         'Reserved zero cave temporarily borrows physical mouse and restores logical mouse/scope'),
    ])
    review = {'changes': [dict(offset=at, size=n, source_sha256=sha(source[at:at+n]),
                              candidate_sha256=sha(candidate[at:at+n]), purpose=why)
                          for at, n, why in spans],
              'appended_size': 0, 'appended_sha256': sha(b'')}
    checked = publisher.native_preserved(source, candidate, review)
    folder.mkdir(); qa.mkdir()
    (folder / 'silver.dll').write_bytes(candidate)
    (qa / 'icons-fixed.dll').write_bytes(icon_fixed)
    (qa / 'hover-only.dll').write_bytes(hover_only)
    package = {'schema': 1, 'previous_version': publisher.PREVIOUS_VERSION,
               'version': publisher.VERSION, 'baseline_manifest_sha256': publisher.MANIFEST_SHA,
               'selection': {'fix': 'battle-ui-quality-and-mine-hover'}, 'native_review': review,
               'files': [dict(path='silver.dll', source='silver.dll', sha256=sha(candidate),
                              size=len(candidate), kind='native')]}
    raw = (json.dumps(package, indent=2) + '\n').encode('utf-8')
    path = folder / 'package.json'; path.write_bytes(raw)
    publisher.load_package(path, sha(raw))
    report = dict(passed=True, package_path=str(path), package_sha256=sha(raw),
                  silver_sha256=sha(candidate), silver_size=len(candidate),
                  icons_fixed_sha256=sha(icon_fixed), hover_only_sha256=sha(hover_only),
                  scope=checked, transforms_commute=True, installed_client_written=False,
                  hosting_written=False, real_client_rendering_verified=False)
    (qa / 'build-proof.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    pe.close()
    return report


if __name__ == '__main__':
    print(json.dumps(build(), indent=2))
