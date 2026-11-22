"""Generate the launcher's per-adapter Silver dependency fingerprint.

The launcher's native adapters were gated by the SHA256 of the whole
silver.dll, so every unrelated client publication silently disabled them.
Each adapter now names the bytes it actually depends on: its own patch sites,
the Silver code/data its injected code calls or reads, and the F7 extension
block it hooks. Expected bytes come from the reviewed base image (the image
the adapters were written for). Uninitialised (.bss) references carry no file
bytes and are skipped.

    python tools/build_launcher_silver_regions.py BASE_SILVER ASSETS_DIR OUT_JSON [--check SILVER]
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pefile

F7_BLOCK = (0x879000, 0x3000)      # baked F7 extension reader/draw block
RECON_SITES = ((0x8798a7, 8), (0x87920c, 6), (0x818bf8, 16))
RAIN_CONSTANT = (0x87f0f8, 8 + 26)  # Delphi header + "gfx\rain.tga" ANSI
TARGET_WINDOW = 16


def adapter_regions(assets: Path) -> dict[str, list[tuple[int, int]]]:
    throwables = json.loads((assets/'native-throwable-effects.json').read_text())
    flame = json.loads((assets/'native-flame-stream.json').read_text())
    contracts = json.loads((assets/'native-contracts-windows.json').read_text())
    regions = {
        'recon': [F7_BLOCK, *RECON_SITES],
        'throwables': [F7_BLOCK, *((p['rva'], len(p['before']) // 2) for p in throwables['patches'])],
        'flame': [F7_BLOCK, *((h['rva'], len(h['before']) // 2) for h in flame['hooks']),
                  *((r['target'], TARGET_WINDOW) for r in flame['relocations'])],
        'rain': [RAIN_CONSTANT],
        'contracts': [*((h['rva'], len(h['before']) // 2) for h in contracts['hooks']),
                      *((r['offset'], TARGET_WINDOW) for block in contracts['blocks']
                        for r in block['relocations'] if r['kind'] == 'silver')],
    }
    return {name: sorted(set(rows)) for name, rows in regions.items()}


def file_bytes(pe: pefile.PE, raw: bytes, rva: int, size: int) -> bytes | None:
    for section in pe.sections:
        start = section.VirtualAddress
        if start <= rva < start + max(section.Misc_VirtualSize, section.SizeOfRawData):
            if rva + size > start + section.SizeOfRawData:
                return None  # uninitialised data has no file bytes
            offset = section.PointerToRawData + rva - start
            return raw[offset:offset + size]
    raise ValueError(f'RVA {rva:#x} is outside every section')


def fingerprint(raw: bytes, regions: dict[str, list[tuple[int, int]]]) -> dict:
    with pefile.PE(data=raw, fast_load=True) as pe:
        result = {}
        for name, rows in regions.items():
            entries = []
            for rva, size in rows:
                data = file_bytes(pe, raw, rva, size)
                if data is not None:
                    entries.append({'rva': rva, 'hex': data.hex()})
            result[name] = entries
        return result


ROOT = Path(__file__).resolve().parents[1]
# Exact copy of the launcher's embedded Assets/native-silver-regions.json.
PLAN = ROOT / 'config/launcher_silver_regions.json'


def mismatches(candidate: bytes, plan: Path = PLAN) -> dict[str, list[int]]:
    """Adapter name -> RVAs whose bytes differ from what the launcher expects."""
    document = json.loads(plan.read_text(encoding='utf-8'))
    result = {}
    with pefile.PE(data=candidate, fast_load=True) as pe:
        for name, rows in document['adapters'].items():
            changed = [row['rva'] for row in rows
                       if file_bytes(pe, candidate, row['rva'], len(row['hex']) // 2) != bytes.fromhex(row['hex'])]
            if changed:
                result[name] = changed
    return result


def require_compatible(candidate: bytes, plan: Path = PLAN) -> None:
    """Refuse a silver.dll that would silently disable published launcher adapters."""
    failed = mismatches(candidate, plan)
    if failed:
        detail = '; '.join(f'{name}: ' + ', '.join(hex(rva) for rva in rvas) for name, rvas in failed.items())
        raise ValueError('silver.dll changes bytes the launcher adapters depend on (' + detail +
                         '). Ship a launcher with regenerated regions first; see docs/LAUNCHER_SILVER_REGIONS_20261114.md')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('base', type=Path)
    parser.add_argument('assets', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--check', type=Path, action='append', default=[])
    args = parser.parse_args()
    raw = args.base.read_bytes()
    regions = adapter_regions(args.assets)
    expected = fingerprint(raw, regions)
    document = {'schema': 1, 'base_sha256': hashlib.sha256(raw).hexdigest(), 'adapters': expected}
    args.output.write_text(json.dumps(document, indent=1) + '\n', encoding='utf-8')
    summary = {name: len(rows) for name, rows in expected.items()}
    print(json.dumps({'written': str(args.output), 'regions': summary}))
    failed = False
    for path in args.check:
        candidate = path.read_bytes()
        changes = mismatches(candidate, args.output)
        failed |= bool(changes)
        verdict = {name: [hex(rva) for rva in changes.get(name, ())] or 'match' for name in expected}
        print(json.dumps({'check': str(path), 'sha256': hashlib.sha256(candidate).hexdigest()[:12],
                          'adapters': verdict}))
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
