"""Owned TLS QA through the original TI Unicode connection adapter.

Uses the established fresh-account/owned-client safeguards and credentials
bridge. Initial connect executes TI71c1b8 (stdcall) and TI718b94, preserving
their original byte-mode behavior. This helper requires the fixed0.1.4 TLS
route. It does not launch clients; the production launcher's readiness files
must identify independent fresh QA copies without login.ini.
"""
from pathlib import Path
import hashlib
import json
import sys

import pefile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import hosted_tls_graphical_qa as tls_qa

TI_SHA = 'e288de090e162660604750075c3e633f60744ee8a24915a9bc24e8cc39ee3f1c'
TI_REFERENCE = Path(r'C:\Program Files (x86)\TIOnline\ti.exe')
BASE_NATIVE_SOURCE = tls_qa.native_source


def adapter_guards():
    raw = TI_REFERENCE.read_bytes()
    tls_qa.require(hashlib.sha256(raw).hexdigest() == TI_SHA, 'Original TI reference changed')
    pe = pefile.PE(data=raw)
    result = []
    try:
        for name, va, size in (('unicode_adapter', 0x71c1b8, 189), ('native_dispatch', 0x718b94, 174)):
            data = pe.get_data(va - 0x400000, size)
            relocations = []
            for block in getattr(pe, 'DIRECTORY_ENTRY_BASERELOC', ()):
                for entry in block.entries:
                    offset = entry.rva - (va - 0x400000)
                    if 0 <= offset < size:
                        tls_qa.require(entry.type == 3 and offset + 4 <= size, 'Unsupported TI adapter relocation')
                        relocations.append(offset)
            result.append(dict(name=name, va=va, code=data.hex(), relocations=relocations))
    finally:
        pe.close()
    return result


def normal_native_source(login_port, session_port):
    source = BASE_NATIVE_SOURCE(login_port, session_port)
    replacements = (
        ('let nativeConnect = null;', 'let nativeConnect = null;\nlet normalHostUnicode = null;\nlet normalKeyUnicode = null;'),
        (f'nativeConnect(Memory.allocUtf8String(EXPECTED_HOST), {login_port}, ptr(0), 0);',
         "nativeConnect(normalHostUnicode, 28512, normalKeyUnicode, 0);\n  emit('native_normal_ti_connect_started', { adapter_va: '0x71c1b8', native_mode_byte: 0, original_host: '185.184.42.88', original_port: 28512 });"),
        ('0x8b,0x44,0x24,0x18,0x83,0xf8,0,0xb8,',
         '0x8b,0x44,0x24,0x18,0x80,0xf8,0,0xb8,'),
        ("    const orange = Process.getModuleByName('orange.dll');\n    nativeConnect = new NativeFunction(orange.getExportByName('AaaAa'), 'void',\n      ['pointer', 'uint32', 'pointer', 'uint32'], 'mscdecl');",
         """    const normalTi = Process.mainModule;
    const normalTiGuards = NORMAL_TI_GUARDS;
    for(const guard of normalTiGuards) {
      const expected = guard.code.match(/../g).map(v => parseInt(v,16));
      const delta = (normalTi.base.toUInt32() - 0x400000) >>> 0;
      for(const offset of guard.relocations) {
        const before = (expected[offset] | expected[offset+1]<<8 | expected[offset+2]<<16 | expected[offset+3]<<24) >>> 0;
        const after = (before + delta) >>> 0;
        for(let index=0; index<4; index++) expected[offset+index] = (after >>> (8*index)) & 255;
      }
      const target = normalTi.base.add(guard.va - 0x400000);
      if(hex(target,expected.length)!==expected.map(v=>v.toString(16).padStart(2,'0')).join(''))
        throw new Error('Original TI adapter code differs');
    }
    normalHostUnicode = delphiString('185.184.42.88').add(12);
    normalKeyUnicode = delphiString('').add(12);
    nativeConnect = new NativeFunction(normalTi.base.add(0x71c1b8 - 0x400000), 'void',
      ['pointer', 'uint32', 'pointer', 'uint32'], 'stdcall');
    emit('native_normal_ti_adapter_verified', { adapter_va:'0x71c1b8', dispatch_va:'0x718b94', abi:'stdcall', byte_mode_contract:true });""".replace('NORMAL_TI_GUARDS', json.dumps(adapter_guards(), separators=(',', ':')))),
    )
    for before, after in replacements:
        tls_qa.require(source.count(before) == 1, 'Established owned QA source changed unexpectedly')
        source = source.replace(before, after)
    tls_qa.require("new NativeFunction(orange.getExportByName('AaaAa')" not in source, 'Direct ORANGE connect remains')
    return source


def main():
    if sys.argv[1:] == ['--source-proof']:
        source = normal_native_source(41001, 41002)
        print(json.dumps(dict(passed=True, source_sha256=hashlib.sha256(source.encode()).hexdigest(),
            ti_sha256=TI_SHA, native_adapter='TI71c1b8 -> TI718b94 -> TLS route', abi='stdcall/ret16',
            fixed_byte_route_guard=True, controlled_unicode_host_and_empty_key=True,
            processes_started=0, credentials_read=False, network_requests=0)))
        return 0
    tls_qa.native_source = normal_native_source
    return tls_qa.main()


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        # Preserve the established no-private-arguments/no-credential error rule.
        print(json.dumps(dict(event='normal_ti_tls_validation_failed', error_type=type(error).__name__)), file=sys.stderr)
        raise SystemExit(1)
