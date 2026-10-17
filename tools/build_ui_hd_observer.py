"""Bind a bounded read-only HD observer to the existing owned display trace."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def build():
    from deploy import client_ui_hd_fonts as fonts
    from deploy import client_ui_hd_icons as icons
    source = ROOT / 'tools/verify_ui_scale_graphical.js'
    addition = ROOT / 'tools/verify_ui_hd_assets_observer.js'
    config = {'fontState': fonts.STATE, 'fontDraw': fonts.DRAW, 'fontTable': fonts.TABLE,
              'fontRows': fonts.FONT_COUNT, 'fontNames': list(fonts.FONTS),
              'iconState': icons.STATE, 'iconTable': icons.ROWS,
              'iconRows': len(icons.RESOURCES),
              'iconFields': [['status',0,'signed'],['loadRows',4],['draws',8],['fallbacks',12],
                             ['lastDensity',16],['lastResource',20],['lastFrame',24],
                             ['nativeTiBase',28,'pointer'],['readyRows',32],['failedRows',36]],
              'markers': [{'rva': fonts.SIGNATURE_RVA, 'text': fonts.SIGNATURE.decode('ascii')},
                          {'rva': icons.SIGNATURE_RVA, 'text': icons.SIGNATURE.decode('ascii')}]}
    prefix = source.read_bytes()
    combined = prefix + b'\nconst HD_OBSERVER_CONFIGURATION=' + json.dumps(config).encode() + b';\n' + addition.read_bytes()
    target = ROOT / 'tools/verify_ui_hd_assets_graphical.js'
    target.write_bytes(combined)
    report = {'result': 'PASS', 'source': str(source),
              'source_sha256': hashlib.sha256(prefix).hexdigest(),
              'native_display_observer_prefix_byte_identical': combined.startswith(prefix),
              'output': str(target), 'sha256': hashlib.sha256(combined).hexdigest(),
              'configuration': config, 'gui_or_gameplay_calls': False,
              'graphical_validation': False}
    out = ROOT / 'reports/ui-hd-assets/graphical/observer-build.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    build()
