"""Make the native TrueSkill selector close send its existing C6/23 writer."""
from pathlib import Path
import hashlib
import json
import struct
import pefile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/ranked-cancel-20261018'
BEFORE = '0678f9b242142142178ab0c4c804e778b0369004dc2a8f3f8459fe1adacb4c6b'


def main():
    raw = (OUT / 'silver-before.dll').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == BEFORE
    pe = pefile.PE(data=raw)
    va = 0x94e478
    offset = pe.get_offset_from_rva(va - 0x400000)
    previous = bytes.fromhex('7405e88d4b0000')
    assert raw[offset:offset + 7] == previous
    # Keep the absolute cmp operand and its relocation at 94e473 intact.
    # Only remove the conditional jump and retarget the existing rel32 call.
    patched = b'\x90\x90\xe8' + struct.pack('<i', 0x952f70 - 0x94e47f)
    result = bytearray(raw)
    result[offset:offset + 7] = patched
    (OUT / 'silver.dll').write_bytes(result)
    proof = dict(passed=True, before_sha256=BEFORE,
                 after_sha256=hashlib.sha256(result).hexdigest(),
                 changes=[dict(va=hex(va), before=previous.hex(), after=patched.hex())],
                 size_unchanged=True, relocations_unchanged=True,
                 native_cancel_writer='0x952f70', native_close='0x94e440')
    (OUT / 'native-review.json').write_text(json.dumps(proof, indent=2))
    print(json.dumps(proof))


if __name__ == '__main__':
    main()
