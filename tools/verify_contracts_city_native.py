"""Build and verify a pinned native city candidate, without client installation."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest

import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_32

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from deploy import client_contracts_city as city

REPORT = ROOT/'reports/contracts-local/city-ui/native'
DEFAULT = ROOT/'reports/contracts-local/clients/game-a/silver.dll'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, default=DEFAULT)
    args = parser.parse_args()
    source = REPORT/'source-silver.dll'
    before = source.read_bytes() if source.is_file() else args.binary.read_bytes()
    if hashlib.sha256(before).hexdigest() != city.BASE_SHA:
        raise ValueError('Verifier requires the pinned original published 2026.10.07.4 source')
    REPORT.mkdir(parents=True, exist_ok=True)
    if not source.is_file():
        source.write_bytes(before)
    updated = city.patch(before)
    plan = city.patch_plan(before, updated)
    candidate = REPORT/'candidate-silver.dll'
    candidate.write_bytes(updated)
    plan['source_path'] = str(source.relative_to(ROOT)).replace('\\','/')
    plan['payload_path'] = str(candidate.relative_to(ROOT)).replace('\\','/')
    (REPORT/'patch-plan.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    sections = []
    for va, code in city.thunks().items():
        sections.append('\n'.join(f'{i.address:08x} {i.bytes.hex():22} {i.mnemonic} {i.op_str}'
            for i in md.disasm(code, va)))
    (REPORT/'city-extension.asm').write_text('\n\n'.join(sections)+'\n', encoding='utf-8')
    spec = importlib.util.spec_from_file_location('contracts_city_native_checks', ROOT/'tests/test_contracts_city_native.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    suite = unittest.defaultTestLoader.loadTestsFromModule(module)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    report = dict(schema=1, passed=result.wasSuccessful(), tests=result.testsRun,
        errors=len(result.errors), failures=len(result.failures),
        source_sha256=plan['source_sha256'], payload_sha256=plan['payload_sha256'],
        aslr_deltas=['0x0','0x1000000'], city_ids=list(city.CITY_IDS),
        checked=['native constructor forwarding and owned parent',
            'dedicated 25px/32px texture loader ABI',
            'separate BSTR captions and UnicodeString paths',
            'registered real native callbacks and preserved registers/flags/stack',
            'visibility reflow of original and new city services',
            'native chat writer opcode21 channel0 UTF16LE NUL',
            'exact source SHA, no overlapping edits, exact idempotence',
            'original existing service callback bytes and PE relocations'],
        graphical_clients=0, network_connections=0, client_installations=0,
        limits=['Scoped native allocation/render API sentinels; graphic rendering and mouse hit testing require a real client.'])
    (REPORT/'probe.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
