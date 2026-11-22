"""Build the launcher adapter that prefers HD map sheets in the "new" interface.

The pinned ti.exe loads every tile texture through one TMemoryStream.LoadFromFile
call (0x6b12f9, EAX=stream, EDX=UnicodeString path) after its basename resolver
has found the original file. The adapter prefers ``.2x.hd`` over ``.hd`` and
then the original. A second call wrapper keeps the logical dimensions at 1x
for marked 2x textures. Both suffixes bypass the native basename resolver.

Usage: python tools/build_native_hd_map_textures.py OUT_JSON
"""
from __future__ import annotations

import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'work/battle-screen-fixes-20261016/deps'))
from keystone import Ks, KS_ARCH_X86, KS_MODE_32  # noqa: E402

BASE = 0x20000000
CALL_SITE = 0x6b12f9
LOAD_FROM_FILE = 0x4b9084
DIMENSIONS_SITE = 0x6b133a
CREATE_TEXTURE = 0x610110
DIMENSIONS_OFFSET = 0x200
GET_FILE_ATTRIBUTES_W_IAT = 0x789408
CALL_SITE_BYTES = bytes.fromhex('e8') + struct.pack('<i', LOAD_FROM_FILE - CALL_SITE - 5)
DIMENSIONS_SITE_BYTES = bytes.fromhex('e8') + struct.pack('<i', CREATE_TEXTURE - DIMENSIONS_SITE - 5)
MAX_PATH_CHARS = 0x280
# Delphi UnicodeString header written in front of the rewritten path:
# code page 1200, element size 2, reference count -1 (constant), length.
SOURCE = f'''
push ebp
mov ebp,esp
sub esp,0x610
push eax
push edx
push ebx
push esi
push edi
mov esi,edx
test esi,esi
jz original
mov ecx,dword ptr [esi-4]
cmp ecx,8
jl original
cmp ecx,{MAX_PATH_CHARS}
ja original
call pattern_base
pattern_base:
pop edi
add edi,pattern-pattern_base
xor ebx,ebx
search:
mov eax,ecx
sub eax,8
cmp ebx,eax
jg original
test ebx,ebx
jz compare
cmp word ptr [esi+ebx*2-2],0x5c
jne advance
compare:
lea edx,[esi+ebx*2]
push ecx
xor ecx,ecx
compare_char:
movzx eax,word ptr [edx+ecx*2]
cmp eax,0x41
jb folded
cmp eax,0x5a
ja folded
or eax,0x20
folded:
cmp ax,word ptr [edi+ecx*2]
jne mismatch
inc ecx
cmp ecx,8
jb compare_char
pop ecx
jmp found
mismatch:
pop ecx
advance:
inc ebx
jmp search
found:
lea edi,[ebp-0x604]
mov word ptr [ebp-0x610],0x4b0
mov word ptr [ebp-0x60e],2
mov dword ptr [ebp-0x60c],-1
lea eax,[ecx+9]
mov dword ptr [ebp-0x608],eax
push ecx
push esi
mov ecx,ebx
cld
rep movsw
mov dword ptr [edi],0x00640068
mov word ptr [edi+4],0x5c
add edi,6
pop esi
pop ecx
push esi
lea esi,[esi+ebx*2]
sub ecx,ebx
rep movsw
pop esi
mov dword ptr [edi],0x0032002e
mov dword ptr [edi+4],0x002e0078
mov dword ptr [edi+8],0x00640068
mov word ptr [edi+12],0
lea eax,[ebp-0x604]
push eax
call dword ptr [{GET_FILE_ATTRIBUTES_W_IAT:#x}]
cmp eax,-1
je legacy_hd
test al,0x10
jz preferred_hd
legacy_hd:
sub dword ptr [ebp-0x608],3
mov dword ptr [edi],0x0068002e
mov dword ptr [edi+4],0x00000064
lea eax,[ebp-0x604]
push eax
call dword ptr [{GET_FILE_ATTRIBUTES_W_IAT:#x}]
cmp eax,-1
je original
test al,0x10
jnz original
preferred_hd:
lea edx,[ebp-0x604]
jmp load
original:
mov edx,dword ptr [ebp-0x618]
load:
mov eax,dword ptr [ebp-0x614]
call {LOAD_FROM_FILE:#x}
pop edi
pop esi
pop ebx
mov esp,ebp
pop ebp
ret
pattern:
'''
PATTERN = 'setting\\'.encode('utf-16le')

# The PNG maker places the zero-length tiOs chunk immediately after IHDR.
# Wrap only the map texture creation call. The four dimensions used for
# normalized UVs and the two cached by map models must all use 1x units.
DIMENSIONS_SOURCE = f'''
push ebp
mov ebp,esp
push esi
push eax
xor esi,esi
cmp dword ptr [edx+8],45
jb create
mov eax,dword ptr [edx+4]
cmp dword ptr [eax],0x474e5089
jne create
cmp dword ptr [eax+4],0x0a1a0a0d
jne create
cmp dword ptr [eax+33],0
jne create
cmp dword ptr [eax+37],0x734f6974
jne create
inc esi
create:
pop eax
push dword ptr [ebp+12]
push dword ptr [ebp+8]
call {CREATE_TEXTURE:#x}
test esi,esi
jz done
test eax,eax
jz done
cmp dword ptr [eax+0xc],0
je done
shr dword ptr [eax+0x14],1
shr dword ptr [eax+0x18],1
shr dword ptr [eax+0x1c],1
shr dword ptr [eax+0x20],1
shr dword ptr [eax+0x24],1
shr dword ptr [eax+0x28],1
done:
pop esi
pop ebp
ret 8
'''


def build() -> dict:
    assembler = Ks(KS_ARCH_X86, KS_MODE_32)
    path_code = bytes(assembler.asm(SOURCE, BASE)[0]) + PATTERN
    if len(path_code) > DIMENSIONS_OFFSET:
        raise ValueError('Path adapter overlaps dimensions adapter')
    dimensions = bytes(assembler.asm(DIMENSIONS_SOURCE, BASE + DIMENSIONS_OFFSET)[0])
    code = path_code.ljust(DIMENSIONS_OFFSET, b'\xcc') + dimensions
    relocations = []
    for target in (LOAD_FROM_FILE, CREATE_TEXTURE):
        sites = [i for i in range(len(code) - 4) if code[i] == 0xe8
                 and BASE + i + 5 + struct.unpack_from('<i', code, i + 1)[0] == target]
        if len(sites) != 1:
            raise ValueError(f'Expected exactly one relocation for {target:#x}')
        relocations.append(dict(offset=sites[0] + 1, target=target))
    # camelCase keys: the launcher deserializes with System.Text.Json defaults.
    return dict(code=code.hex(), callSite=CALL_SITE, callSiteBytes=CALL_SITE_BYTES.hex(),
                dimensionsSite=DIMENSIONS_SITE, dimensionsSiteBytes=DIMENSIONS_SITE_BYTES.hex(),
                dimensionsOffset=DIMENSIONS_OFFSET, relocations=relocations)


def code_at(plan: dict, allocation: int) -> bytes:
    """Mirror the launcher relocation (NativeHdMapTextures.Build)."""
    code = bytearray.fromhex(plan['code'])
    for relocation in plan['relocations']:
        offset = relocation['offset']
        struct.pack_into('<i', code, offset, relocation['target'] - allocation - offset - 4)
    return bytes(code)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    Path(sys.argv[1]).write_text(json.dumps(build(), indent=2) + '\n', encoding='utf-8')
    print('Built native HD map texture adapter')
