"""Follow direct x86 branches in a mapped image, skipping jump-over junk bytes."""
import argparse
from pathlib import Path
import capstone
from capstone.x86 import X86_OP_IMM

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('image',type=Path)
    ap.add_argument('base',type=lambda s:int(s,0))
    ap.add_argument('entry',type=lambda s:int(s,0))
    ap.add_argument('--limit',type=int,default=600)
    a=ap.parse_args(); raw=a.image.read_bytes()
    md=capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_32); md.detail=True
    pending=[a.entry]; seen=set()
    while pending and len(seen)<a.limit:
        pc=pending.pop()
        while pc not in seen and len(seen)<a.limit:
            offset=pc-a.base
            if not 0<=offset<len(raw): break
            ins=next(md.disasm(raw[offset:offset+15],pc,count=1),None)
            if not ins: break
            seen.add(pc)
            print(f'{pc-a.base:05x} {ins.bytes.hex():24} {ins.mnemonic:8} {ins.op_str}')
            jump=ins.group(capstone.CS_GRP_JUMP)
            if jump:
                target=ins.operands[0].imm if ins.operands[0].type==X86_OP_IMM else None
                if ins.mnemonic=='jmp':
                    if target is None: break
                    pc=target; continue
                if target is not None: pending.append(target)
            if ins.group(capstone.CS_GRP_RET): break
            pc+=ins.size

if __name__=='__main__': main()
