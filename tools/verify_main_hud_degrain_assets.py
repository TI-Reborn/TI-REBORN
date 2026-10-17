"""Read-only independent verification of the scoped native HUD asset package."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import sys

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.build_visual_asset_catalog import decode
from tools.native_texture_contract_hud import inspect_texture, validate_replacement

OUT = ROOT / 'reports/gameplay-completion/legacy-status-20261011/textures-main-hud'
EXPECTED = {'base/pda/' + name for name in (
    'gui_main_1-1.png','gui_main_1-2.png','gui_main_1-22.png','gui_main_1-3.png',
    'gui_main_1-4.png','gui_main_1-6.png','gui_main_1-7.png','gui_main_1-8.png',
    'gui_main_1-82.png','gui_main_1-9.png','gui_main_vbar.png','gui_chat_h.png','loc_reserve.jpg')}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def activity(image, box):
    image = image.convert('L').crop(box)
    data, width, height = image.tobytes(), image.width, image.height
    differences = []
    for y in range(height):
        for x in range(width):
            i = y * width + x
            if x + 1 < width: differences.append(abs(data[i]-data[i+1]))
            if y + 1 < height: differences.append(abs(data[i]-data[i+width]))
    return sum(differences) / len(differences)


def main():
    inventory = json.loads((OUT/'changed-files.json').read_bytes())
    baseline = json.loads((OUT/'baseline-manifest.json').read_bytes())
    records = {r['path']:r for r in baseline['files']}
    assert inventory['baseline_version'] == baseline['version'] == '2026.10.11.2'
    assert sha((OUT/'baseline-manifest.json').read_bytes()) == inventory['baseline_manifest_sha256']
    assert {r['path'] for r in inventory['files']} == EXPECTED
    assert len(inventory['files']) == inventory['changed_count'] == 13
    pairs = []
    rejected_alpha_mutations = 0
    for record in inventory['files']:
        source_path = OUT/'source'/record['path']
        target_path = OUT/'candidate'/record['path']
        before, after = source_path.read_bytes(), target_path.read_bytes()
        assert sha(before) == records[record['path']]['sha256'] == record['original_sha256']
        assert len(before) == records[record['path']]['size'] == record['original_size']
        assert sha(after) == record['sha256'] and len(after) == record['size']
        assert sha((OUT/record['master']).read_bytes()) == record['master_sha256']
        contract = validate_replacement(before, after)
        for key,value in contract.items():
            assert record.get('native_codec' if key == 'codec' else key) == value
        old, _ = decode(before)
        new, _ = decode(after)
        assert old.size == new.size == tuple(record['dimensions'])
        assert old.getchannel('A').tobytes() == new.getchannel('A').tobytes()
        if record['native_codec'] != 'JPEG':
            for box in record['protected_original_rectangles']:
                assert old.crop(box).tobytes() == new.crop(box).tobytes(), ('Protected bitmap changed',record['path'],box)
            w,h = old.size
            for box in ((0,0,w,2),(0,h-2,w,h),(0,0,2,h),(w-2,0,w,h)):
                assert old.crop(box).tobytes() == new.crop(box).tobytes(), ('Native seam changed',record['path'])
        if record['native_codec'] == 'BMP32':
            changed = bytearray(after)
            changed[contract['pixel_offset']+3] ^= 1
            try: validate_replacement(before, bytes(changed))
            except ValueError: rejected_alpha_mutations += 1
            else: raise AssertionError('BMP alpha mutation accepted')
        pairs.extend((str(source_path.resolve()),str(target_path.resolve())))
    assert (OUT/'native-decoder-pairs.txt').read_text().splitlines() == pairs
    native = json.loads((OUT/'native-d3dx-proof.json').read_text(encoding='utf-8-sig'))
    assert native['passed'] and native['pair_count'] == 13
    for i,pair in enumerate(native['pairs']):
        assert pair['invariants_equal'] and pair['before']['Path'] == pairs[i*2] and pair['after']['Path'] == pairs[i*2+1]
    old_inventory = ROOT/'reports/gameplay-completion/legacy-status-20261011/textures/changed-files.json'
    assert sha(old_inventory.read_bytes()) == inventory['prior_published_inventory_sha256']
    samples = []
    for name,box in (
        ('gui_main_1-7.png',(20,15,118,61)),
        ('gui_main_1-8.png',(80,24,220,35)),
        ('gui_main_1-9.png',(20,18,145,30)),
        ('gui_chat_h.png',(10,10,245,20)),
        ('loc_reserve.jpg',(0,0,1024,110))):
        old,_ = decode((OUT/'source/base/pda'/name).read_bytes())
        new,_ = decode((OUT/'candidate/base/pda'/name).read_bytes())
        a,b = activity(old,box), activity(new,box)
        samples.append(dict(path='base/pda/'+name,rectangle=box,
                            before_mean_adjacent_luminance_difference=a,
                            after_mean_adjacent_luminance_difference=b,
                            reduction_percent=100*(1-b/a)))
    proof = dict(passed=True,changed_count=13,contract_pairs=13,native_d3dx_pairs=13,
                 exact_alpha_pairs=13,exact_seam_pairs=12,protected_text_icon_pairs=2,
                 bmp_alpha_mutations_rejected=rejected_alpha_mutations,
                 inventory_sha256=sha((OUT/'changed-files.json').read_bytes()),
                 contract_tool_sha256=sha((ROOT/'tools/native_texture_contract_hud.py').read_bytes()),
                 visual_review=['review-1.png','review-2.png','review-3.png'],
                 grain_sample_activity=samples,
                 metric_limit='Local high-frequency activity includes coherent scratches/mesh; not proof of zero noise in all assets',
                 remaining_bitmaps=2304)
    (OUT/'verification-summary.json').write_text(json.dumps(proof,indent=2)+'\n')
    print(json.dumps(proof))


if __name__ == '__main__':
    main()
