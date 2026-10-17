"""Read-only Contracts investigation of the original Silver build.

Writes only reports/contracts-local/native. No client mutation or network calls.
Addresses in this report are preferred virtual addresses, not runtime ASLR addresses.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_32

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BINARY = ROOT / "reports/client-version-research/archive-20231004/silver.dll"
EXPECTED_SHA = "a73396748ea5c3530157db53592a9f3e04744592c3711f38d40d4877b785de11"
REPORT_DIR = ROOT / "reports/contracts-local/native"


class NativeImage:
    def __init__(self, binary: Path = DEFAULT_BINARY):
        self.binary = binary
        raw = binary.read_bytes()
        self.sha256 = hashlib.sha256(raw).hexdigest()
        if self.sha256 != EXPECTED_SHA:
            raise ValueError("Unknown Silver build; re-establish addresses before investigating")
        self.pe = pefile.PE(data=raw)
        self.base = self.pe.OPTIONAL_HEADER.ImageBase
        self.data = self.pe.get_memory_mapped_image()
        self.md = Cs(CS_ARCH_X86, CS_MODE_32)

    def refs(self, address: int) -> list[int]:
        needle = struct.pack("<I", address)
        result, start = [], 0
        while (position := self.data.find(needle, start)) >= 0:
            result.append(self.base + position)
            start = position + 1
        return result

    def calls(self, address: int) -> list[int]:
        result = []
        for position in range(len(self.data) - 5):
            if self.data[position] == 0xE8:
                displacement = struct.unpack_from("<i", self.data, position + 1)[0]
                if self.base + position + 5 + displacement == address:
                    result.append(self.base + position)
        return result

    def disasm(self, address: int, count: int) -> str:
        offset = address - self.base
        if not 0 <= offset < len(self.data) or not 1 <= count <= 32768:
            raise ValueError("Disassembly range outside bounded image")
        return "\n".join(
            f"{i.address:08x}  {i.bytes.hex():<24} {i.mnemonic:<8} {i.op_str}"
            for i in self.md.disasm(self.data[offset:offset + count], address)
        ) + "\n"

    def strings(self) -> list[dict]:
        rows = json.loads((ROOT / "evidence/TI.silver.dll.strings.json").read_text(encoding="utf-8"))
        needles = ("party", "quest", "town", "contracts")
        result = []
        for row in rows:
            value = row["string"]
            if len(value) <= 120 and any(needle in value.casefold() for needle in needles):
                address = self.base + self.pe.get_rva_from_offset(row["offset"])
                result.append({"string": value, "va": hex(address), "refs": [hex(a) for a in self.refs(address)]})
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    parser.add_argument("--disasm", type=lambda s: int(s, 0))
    parser.add_argument("--bytes", type=int, default=512)
    parser.add_argument("--calls", type=lambda s: int(s, 0))
    args = parser.parse_args()
    image = NativeImage(args.binary)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    if args.disasm is not None:
        text = image.disasm(args.disasm, args.bytes)
        (REPORT_DIR / f"silver-{args.disasm:08x}.asm").write_text(text, encoding="utf-8")
        print(text)
    elif args.calls is not None:
        print(json.dumps([hex(a) for a in image.calls(args.calls)]))
    else:
        report = {"sha256": image.sha256, "binary": str(image.binary), "address_kind": "preferred VA", "strings": image.strings()}
        (REPORT_DIR / "string-xrefs.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps([r for r in report["strings"] if "party" in r["string"].casefold() or "quest" in r["string"].casefold()], ensure_ascii=False))


if __name__ == "__main__":
    main()
