"""Encode reviewed ImageGen HUD edits into unchanged native layouts.

Only canvas registration, resolution adaptation, exact alpha restoration and
protected original pixel transfer are performed. No procedural image cleanup.
"""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path
import sys

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.build_visual_asset_catalog import decode
from tools.equipment_texture_export import native_encode
from tools.native_texture_contract_hud import validate_replacement

OUT = ROOT / 'reports/gameplay-completion/legacy-status-20261011/textures-main-hud'
BASELINE_SHA = 'f28a1f36ed14414df565f47826ed522ea3db60e81dedb239ed6983351d2aea99'
OLD_INVENTORY_SHA = '8963f669c002640ea776ef6b89bcad51676895cf9c646b22d9eca6302a8dbe27'
NAMES = ('gui_main_1-1.png', 'gui_main_1-2.png', 'gui_main_1-22.png',
         'gui_main_1-3.png', 'gui_main_1-4.png', 'gui_main_1-6.png',
         'gui_main_1-7.png', 'gui_main_1-8.png', 'gui_main_1-82.png',
         'gui_main_1-9.png', 'gui_main_vbar.png', 'gui_chat_h.png', 'loc_reserve.jpg')
PROTECTED = {'gui_main_1-1.png': [(37, 260, 125, 313), (61, 0, 111, 225), (160, 347, 256, 512)],
             'gui_main_1-2.png': [(0, 88, 61, 256), (181, 88, 256, 256)],
             'gui_main_1-3.png': [(65, 348, 183, 512), (0, 348, 38, 512)],
             'gui_main_1-4.png': [(39, 0, 91, 128)],
             'gui_main_1-6.png': [(23, 0, 45, 86)],
             'gui_main_1-7.png': [(54, 95, 107, 143), (54, 165, 107, 214),
                                  (54, 239, 107, 287), (54, 310, 107, 358)]}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def original_png_metadata(raw: bytes, encoded: bytes) -> bytes:
    def chunks(payload):
        offset = 8
        result = []
        while offset < len(payload):
            length = struct.unpack_from('>I', payload, offset)[0]
            end = offset + 12 + length
            result.append((payload[offset+4:offset+8], payload[offset:end]))
            offset = end
        return result
    original, fresh = chunks(raw), chunks(encoded)
    assert original[0][1] == fresh[0][1], 'PNG IHDR must remain identical'
    idat = b''.join(chunk for kind,chunk in fresh if kind == b'IDAT')
    result, inserted = bytearray(raw[:8]), False
    for kind,chunk in original:
        if kind == b'IDAT':
            if not inserted:
                result.extend(idat)
                inserted = True
        else:
            result.extend(chunk)
    assert inserted
    return bytes(result)


def registered_art(name: str, master: Image.Image, reference: Image.Image):
    # ImageGen can pad very narrow inputs. The reviewed crop registers their
    # visible strip against native pixel boundaries rather than stretching pads.
    crop = None
    if name == 'gui_main_1-8.png':
        assert master.size == (2170, 725)
        scale = master.width / reference.width
        crop = (0.0, 87.0, 2170.0, 87.0 + reference.height * scale)
    elif name == 'gui_main_1-6.png':
        assert master.size == (724, 2172)
        scale = master.height / reference.height
        left = 182.0 - 8.0 * scale
        crop = (left, 0.0, left + reference.width * scale, 2172.0)
    elif name == 'gui_main_vbar.png':
        assert master.size == (724, 2172)
        crop = (241.0, 0.0, 484.0, 2172.0)
    art = master.convert('RGBA').resize(reference.size, Image.Resampling.LANCZOS, box=crop)
    if name == 'gui_main_1-82.png':
        assert master.size == (1774, 887)
        crop = (0, 121, 1774, 731)
        art = reference.copy()
        art.paste(master.convert('RGBA').crop(crop).resize((128,44),Image.Resampling.LANCZOS),(0,10))
    art.putalpha(reference.getchannel('A'))
    # Exact original seam pixels protect joined slices. Native transparent and
    # transition pixels keep their original RGB to prevent matte colour fringes.
    if name != 'loc_reserve.jpg':
        pixels, old = bytearray(art.tobytes()), reference.tobytes()
        width, height = reference.size
        alphas = old[3::4]
        protected_count = 0
        for y in range(height):
            for x in range(width):
                i = y * width + x
                edge = x < 2 or y < 2 or x >= width-2 or y >= height-2
                a = alphas[i]
                transition = a < 255
                if not transition and a:
                    transition = any(alphas[ny * width + nx] < 255
                                     for nx, ny in ((x-1,y),(x+1,y),(x,y-1),(x,y+1))
                                     if 0 <= nx < width and 0 <= ny < height)
                roi = any(l <= x < r and t <= y < b for l,t,r,b in PROTECTED.get(name, []))
                if edge or transition or roi:
                    pixels[i*4:i*4+4] = old[i*4:i*4+4]
                    protected_count += 1
        art = Image.frombytes('RGBA', reference.size, bytes(pixels))
    else:
        protected_count = 0
    return art, crop, protected_count


def build():
    if (OUT / 'FROZEN.json').exists():
        raise RuntimeError('Reviewed main HUD inventory is frozen; create a separate new package for further edits')
    baseline_raw = (OUT / 'baseline-manifest.json').read_bytes()
    assert sha(baseline_raw) == BASELINE_SHA
    baseline = json.loads(baseline_raw)
    assert baseline['version'] == '2026.10.11.2' and len(baseline['files']) == 6567
    records = {r['path']: r for r in baseline['files']}
    old_inventory = ROOT / 'reports/gameplay-completion/legacy-status-20261011/textures/changed-files.json'
    assert sha(old_inventory.read_bytes()) == OLD_INVENTORY_SHA
    proofs, native_pairs = [], []
    for name in NAMES:
        relative = 'base/pda/' + name
        source = OUT / 'source' / relative
        raw = source.read_bytes()
        record = records[relative]
        assert sha(raw) == record['sha256'] and len(raw) == record['size'] and not record.get('seed')
        reference, _ = decode(raw)
        provenance_path = OUT / 'provenance' / (name + '.round2.json')
        if not provenance_path.exists():
            provenance_path = OUT / 'provenance' / (name + '.json')
        provenance = json.loads(provenance_path.read_text())
        master_path = Path(provenance['master'])
        master = Image.open(master_path)
        art, crop, protected_count = registered_art(name, master, reference)
        data = native_encode(raw, art, reference)
        if raw.startswith(b'\x89PNG'):
            data = original_png_metadata(raw, data)
        contract = validate_replacement(raw, data)
        check, _ = decode(data)
        assert check.size == reference.size
        assert check.getchannel('A').tobytes() == reference.getchannel('A').tobytes()
        destination = OUT / 'candidate' / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        preview = OUT / 'review-decoded' / (name + '.png')
        preview.parent.mkdir(parents=True, exist_ok=True)
        check.save(preview)
        native_pairs.extend((str(source.resolve()), str(destination.resolve())))
        proofs.append(dict(path=relative, original_sha256=sha(raw), original_size=len(raw),
                           sha256=sha(data), size=len(data), dimensions=list(check.size),
                           native_codec=contract['codec'], original_alpha_exact=True, seed=False,
                           master=str(master_path.relative_to(OUT)).replace('\\', '/'),
                           master_sha256=sha(master_path.read_bytes()), source_geometry_crop=crop,
                           provenance=str(provenance_path.relative_to(OUT)).replace('\\', '/'),
                           protected_original_pixels=protected_count,
                           protected_original_rectangles=PROTECTED.get(name, []),
                           layout='exact native canvas/alpha, original two-pixel seams and transition pixels',
                           **{k:v for k,v in contract.items() if k != 'codec'}))
    report = dict(baseline_version='2026.10.11.2', baseline_manifest_sha256=BASELINE_SHA,
                  operation='ImageGen reference cleanup; native canvas registration and exact original alpha',
                  files=proofs, changed_count=len(proofs), total_size=sum(r['size'] for r in proofs),
                  executables_modified=False, model_uv_or_xml_modified=False,
                  prior_published_inventory_sha256=OLD_INVENTORY_SHA)
    (OUT / 'changed-files.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    (OUT / 'native-decoder-pairs.txt').write_text('\n'.join(native_pairs) + '\n', encoding='utf-8')
    print(json.dumps(dict(changed=len(proofs), total_size=report['total_size'],
                         inventory_sha256=sha((OUT/'changed-files.json').read_bytes()))))


if __name__ == '__main__':
    build()
