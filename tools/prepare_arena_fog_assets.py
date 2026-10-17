"""Set a constant native foreground tint; retain every pixel and map byte."""
import hashlib
import json
import shutil
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'assets/arena-surroundings-v1/client-overlay'
TARGET = ROOT/'assets/arena-surroundings-v2/client-overlay'
REPORT = ROOT/'assets/arena-surroundings-v2/fog-proof.json'
BEFORE = ROOT/'reports/arena-surroundings-fog/previous-client-manifest.json'
TINT = 0x00b1b1b1


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    previous = json.loads(BEFORE.read_text('utf-8'))
    assert previous['version'] == '2026.10.07.1'
    old = {row['path']: row for row in previous['files']}
    paths = sorted(p for p in SOURCE.rglob('*') if p.is_file())
    assert len(paths) == 1128
    changes, files = [], []
    for path in paths:
        name = path.relative_to(SOURCE).as_posix()
        raw = path.read_bytes()
        assert len(raw) == old[name]['size'] and digest(raw) == old[name]['sha256'], name
        result = raw
        if path.suffix == '.t':
            assert len(raw) == 544 and raw[:8] == b'TI TILE\0'
            assert struct.unpack_from('<II', raw, 52) == (0x00ffffff, 255)
            assert raw[68:70] == b'\x01\0' and raw[340:356] == bytes(16)
            modified = bytearray(raw)
            struct.pack_into('<I', modified, 52, TINT)
            result = bytes(modified)
            offsets = [i for i, (a, b) in enumerate(zip(raw, result)) if a != b]
            assert offsets == [52, 53, 54]
            changes.append(dict(path=name, old_sha256=digest(raw), sha256=digest(result),
                                size=len(result), changed_offsets=offsets))
        target = TARGET/name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            assert target.read_bytes() == result, 'A different prepared asset already exists: '+name
        elif result == raw:
            shutil.copy2(path, target)
        else:
            target.write_bytes(result)
        assert target.read_bytes() == result
        files.append(dict(path=name, size=len(result), sha256=digest(result)))
    assert len(changes) == 552
    assert sum(p.suffix == '.s' for p in paths) == 24
    assert sum(p.suffix == '.png' for p in paths) == 552
    assert {p.relative_to(TARGET).as_posix() for p in TARGET.rglob('*') if p.is_file()} == {r['path'] for r in files}
    report = dict(schema='arena-surroundings-fog/v1', passed=True,
        previous_version='2026.10.07.1', client_version='2026.10.07.2',
        tint_rgb_hex='b1b1b1', native_vertex_argb='ffb1b1b1', native_alpha=255,
        fixed_darkening_fraction=78/255, tint_bytes=[177, 177, 177],
        changed_offsets=[52, 53, 54], changed_tile_count=552, scene_count=24,
        pngs_unchanged=552, scenes_unchanged=24, inventory_file_count=1128,
        previous_manifest_sha256=digest(BEFORE.read_bytes()),
        original_asset_proof_sha256=digest((ROOT/'reports/arena-surroundings-implementation/asset-proof.json').read_bytes()),
        source_png_pixels_and_alpha_unchanged=True, gameplay_holes_and_all_four_sides_unchanged=True,
        model_anchors_dimensions_uv_flags_and_interactions_unchanged=True,
        treatment='Constant type1 foreground RGB tint matching the primary native fog.tga center alpha78; never tied to sight or exploration.',
        scope='All24 existing city surroundings scenes (four cities, three variants,38/57). Other battle families retain their original opaque black outside.',
        changes=changes, files=files)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', 'utf-8')
    print(json.dumps(dict(passed=True, changed_tiles=552, changed_offsets=[52, 53, 54],
        unchanged_pngs=552, unchanged_scenes=24, tint='b1b1b1', report=str(REPORT))))


if __name__ == '__main__':
    main()
