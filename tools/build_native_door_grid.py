"""Assemble the bounded native door adapter used by TIO Launcher.

The pinned ti.exe uses a fixed image base, as does its existing TLS adapter.
Internal calls are relative. Only the two trampoline jumps need allocation
relocation. No network permissions, AP or authoritative actor state change.
"""
import json
from pathlib import Path
import struct
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'work/battle-screen-fixes-20261016/deps'))
from keystone import Ks,KS_ARCH_X86,KS_MODE_32

BASE=0x20000000
PARTS={
0x000: '''
pushfd
pushad
call 0x20000200
popad
popfd
call 0x20000040
pushfd
pushad
call 0x20000400
call 0x20000600
popad
popfd
ret
''',
0x040: '''
push ebp
mov ebp,esp
add esp,-0x30
jmp 0x6e40aa
''',
0x080: '''
cmp byte ptr [esp+4],1
jne original
cmp dword ptr [esp+8],3
je stable
cmp dword ptr [esp+8],4
jne original
stable:
sub dword ptr [esp+8],2
original:
push ebp
mov ebp,esp
add esp,-0x20
jmp 0x72dc96
''',
# EAX=grid, EDX=scene items, ECX=count. Zero EAX if no valid battle.
0x100: '''
mov eax,dword ptr [0x76e000]
test eax,eax
jz fail
mov eax,dword ptr [eax]
test eax,eax
jz fail
mov eax,dword ptr [eax+0xd0]
test eax,eax
jz fail
mov ecx,dword ptr [eax+8]
test ecx,ecx
jle fail
cmp ecx,10000
ja fail
mov edx,dword ptr [eax+4]
test edx,edx
jz fail
mov eax,dword ptr [0x76e5f4]
test eax,eax
jz fail
mov eax,dword ptr [eax]
test eax,eax
jz fail
cmp word ptr [eax+0x24],0
je fail
cmp word ptr [eax+0x24],128
ja fail
cmp word ptr [eax+0x26],0
je fail
cmp word ptr [eax+0x26],128
ja fail
cmp dword ptr [eax+12],0
je fail
cmp dword ptr [eax+28],0
je fail
ret
fail:
xor eax,eax
ret
''',
0x200: '''
call 0x20000100
test eax,eax
jz done
mov ebx,eax
mov esi,edx
mov edi,ecx
next:
mov edx,dword ptr [esi]
add esi,4
test edx,edx
jz skip
movzx ebp,byte ptr [edx+0x340]
cmp ebp,3
je pending
cmp ebp,4
jne settled
pending:
sub ebp,2
mov byte ptr [edx+0x340],bpl_placeholder
settled:
cmp ebp,1
je door
cmp ebp,2
jne skip
door:
mov eax,dword ptr [edx+4]
mov ecx,dword ptr [edx+8]
test eax,eax
js skip
test ecx,ecx
js skip
movzx edx,word ptr [ebx+0x24]
cmp eax,edx
jae skip
movzx edx,word ptr [ebx+0x26]
cmp ecx,edx
jae skip
mov edx,dword ptr [ebx+12]
mov edx,dword ptr [edx+eax*4]
imul ecx,ecx,14
cmp ebp,1
jne opened
mov byte ptr [edx+ecx],3
jmp skip
opened:
mov byte ptr [edx+ecx],0
skip:
dec edi
jnz next
done:
ret
''',
# Stack locals: grid, item vector, count, index, door, owner, key, actors,
# door x, door y, actor index. Reveal only closed surfaces one cell away.
0x400: '''
push ebp
mov ebp,esp
sub esp,44
call 0x20000100
test eax,eax
jz done
mov dword ptr [ebp-4],eax
mov dword ptr [ebp-8],edx
mov dword ptr [ebp-12],ecx
mov dword ptr [ebp-16],0
mov eax,dword ptr [0x76dfac]
test eax,eax
jz done
mov eax,dword ptr [eax]
mov dword ptr [ebp-24],eax
mov eax,dword ptr [0x76e068]
test eax,eax
jz done
movzx eax,word ptr [eax]
mov dword ptr [ebp-28],eax
mov eax,dword ptr [0x76e430]
test eax,eax
jz done
mov dword ptr [ebp-32],eax
nextdoor:
mov eax,dword ptr [ebp-8]
mov ecx,dword ptr [ebp-16]
mov edx,dword ptr [eax+ecx*4]
test edx,edx
jz skipdoor
cmp byte ptr [edx+0x340],1
jne skipdoor
mov dword ptr [ebp-20],edx
mov eax,dword ptr [edx+4]
mov ecx,dword ptr [edx+8]
test eax,eax
js skipdoor
test ecx,ecx
js skipdoor
mov ebx,dword ptr [ebp-4]
movzx edx,word ptr [ebx+0x24]
cmp eax,edx
jae skipdoor
movzx edx,word ptr [ebx+0x26]
cmp ecx,edx
jae skipdoor
mov dword ptr [ebp-36],eax
mov dword ptr [ebp-40],ecx
mov dword ptr [ebp-44],0
nextactor:
mov eax,dword ptr [ebp-32]
mov ecx,dword ptr [ebp-44]
mov esi,dword ptr [eax+ecx*4]
test esi,esi
jz skipactor
mov eax,dword ptr [ebp-24]
cmp dword ptr [esi+0x64],eax
jne skipactor
movzx eax,word ptr [esi+8]
xor eax,dword ptr [ebp-28]
test ax,ax
jz skipactor
mov eax,dword ptr [esi+0x1bc]
mov ecx,dword ptr [esi+0x1c0]
test eax,eax
js skipactor
test ecx,ecx
js skipactor
movzx edx,word ptr [ebx+0x24]
cmp eax,edx
jae skipactor
movzx edx,word ptr [ebx+0x26]
cmp ecx,edx
jae skipactor
mov edi,eax
sub edi,dword ptr [ebp-36]
add edi,1
cmp edi,2
ja skipactor
mov edx,ecx
sub edx,dword ptr [ebp-40]
add edx,1
cmp edx,2
ja skipactor
cmp edi,1
je aligned
cmp edx,1
je reveal
jmp reveal
aligned:
cmp edx,1
je skipactor
reveal:
mov eax,dword ptr [ebx+28]
mov ecx,dword ptr [ebp-36]
mov eax,dword ptr [eax+ecx*4]
mov ecx,dword ptr [ebp-40]
imul ecx,ecx,6
mov byte ptr [eax+ecx],1
jmp skipdoor
skipactor:
inc dword ptr [ebp-44]
cmp dword ptr [ebp-44],31
jb nextactor
skipdoor:
inc dword ptr [ebp-16]
mov eax,dword ptr [ebp-16]
cmp eax,dword ptr [ebp-12]
jb nextdoor
done:
mov esp,ebp
pop ebp
ret
''',
# Authoritative F7 recon cells; pointers are bound only after the pinned Silver
# loads. Run AFTER stock fog reset and door surfaces, never extend LOS/range.
0x600: '''
call here
here:
pop edi
sub edi,0x605
mov esi,dword ptr [edi+0xf00]
test esi,esi
jz done
mov ebp,dword ptr [esi]
test ebp,ebp
jz done
cmp ebp,4096
ja done
mov esi,dword ptr [edi+0xf04]
test esi,esi
jz done
mov ebx,dword ptr [0x76e5f4]
test ebx,ebx
jz done
mov ebx,dword ptr [ebx]
test ebx,ebx
jz done
cmp word ptr [ebx+0x24],0
je done
cmp word ptr [ebx+0x24],128
ja done
cmp word ptr [ebx+0x26],0
je done
cmp word ptr [ebx+0x26],128
ja done
mov edi,dword ptr [ebx+28]
test edi,edi
jz done
next:
cmp byte ptr [esi+2],3
jne skip
movzx eax,byte ptr [esi]
movzx ecx,byte ptr [esi+1]
movzx edx,word ptr [ebx+0x24]
cmp eax,edx
jae skip
movzx edx,word ptr [ebx+0x26]
cmp ecx,edx
jae skip
mov eax,dword ptr [edi+eax*4]
test eax,eax
jz skip
imul ecx,ecx,6
mov byte ptr [eax+ecx],1
skip:
add esi,3
dec ebp
jnz next
done:
ret
''',
# Replaces the exact F7 reader tail. Both valid/empty and malformed snapshots
# trigger a fresh native fog calculation, so expired cells do not linger.
0x800: '''
mov dword ptr [esp+28],1
popad
popfd
pushfd
pushad
mov eax,dword ptr [0x76e5f4]
test eax,eax
jz done
mov eax,dword ptr [eax]
test eax,eax
jz done
cmp dword ptr [eax+28],0
je done
call 0x6e40a4
done:
popad
popfd
ret
'''
}

def build():
    # x86 has no BPL. Save EAX while normalizing a pre-existing deferred door.
    PARTS[0x200]=PARTS[0x200].replace('mov byte ptr [edx+0x340],bpl_placeholder', '''
push eax
mov eax,ebp
mov byte ptr [edx+0x340],al
add al,byte ptr [edx+0x411]
dec al
mov byte ptr [edx+0x28],al
pop eax''')
    ks=Ks(KS_ARCH_X86,KS_MODE_32);blob=bytearray(4096);relocations=[]
    for offset,source in PARTS.items():
        raw=bytes(ks.asm(source,BASE+offset)[0])
        assert offset+len(raw)<=min((x for x in PARTS if x>offset),default=0xf00)
        blob[offset:offset+len(raw)]=raw
        for target in (0x6e40aa,0x72dc96):
            marker=b'\xe9'+struct.pack('<i',target-(BASE+offset+len(raw)))
            if raw.endswith(marker):relocations.append(dict(offset=offset+len(raw)-4,target=target))
        if offset==0x800:
            marker=b'\xe8'+struct.pack('<i',0x6e40a4-(BASE+offset+raw.index(b'\xe8')+5))
            at=raw.index(marker);relocations.append(dict(offset=offset+at+1,target=0x6e40a4))
    assert len(relocations)==3
    return dict(schema=1,base=BASE,code=blob.hex(),fogEntry=0,doorEntry=128,
                relocations=relocations,scope='Pinned ti.exe door collision and adjacent closed surface only')

if __name__=='__main__':
    result=build()
    (ROOT/'launcher/Assets/native-door-grid.json').write_text(json.dumps(result,indent=2)+'\n')
    print('Built native door adapter:',len(bytes.fromhex(result['code'])),'bytes')
