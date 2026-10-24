"""Build the pinned ti.exe YourTurn selection adapter; no gameplay packets."""
import json,struct,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'work/battle-screen-fixes-20261016/deps'))
from keystone import Ks,KS_ARCH_X86,KS_MODE_32
BASE=0x20000000
SOURCE='''
pushfd
pushad
mov eax,dword ptr [0x76dfac]
test eax,eax
jz done
mov edx,dword ptr [eax]
mov esi,dword ptr [0x76e430]
test esi,esi
jz done
mov eax,dword ptr [0x76e068]
test eax,eax
jz done
movzx edi,byte ptr [eax]
xor ecx,ecx
next:
mov ebx,dword ptr [esi+ecx*4]
test ebx,ebx
jz skip
cmp dword ptr [ebx+0x64],edx
jne skip
movzx eax,word ptr [ebx+8]
xor eax,edi
test ax,ax
jz skip
mov eax,ecx
call 0x706564
jmp done
skip:
inc ecx
cmp ecx,31
jb next
done:
popad
popfd
jmp 0x71ea08
'''

def build():
    raw=bytes(Ks(KS_ARCH_X86,KS_MODE_32).asm(SOURCE,BASE)[0]);relocations=[]
    for opcode,target in ((0xe8,0x706564),(0xe9,0x71ea08)):
        sites=[i for i in range(len(raw)-4) if raw[i]==opcode and BASE+i+5+struct.unpack_from('<i',raw,i+1)[0]==target]
        assert len(sites)==1
        relocations.append(dict(offset=sites[0]+1,target=target))
    return dict(code=raw.hex(),relocations=relocations)

if __name__=='__main__':
    (ROOT/'launcher/Assets/native-battle-turn.json').write_text(json.dumps(build(),indent=2)+'\n')
    print('Built native YourTurn adapter')
