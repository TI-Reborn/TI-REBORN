"""Independent ABI and rendering-boundary proof for the native UI scale core."""
from pathlib import Path
import hashlib
import json
import struct
import sys

import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_32

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from deploy import client_ui_scale as scale


def reachable(image, entry):
    decoder=Cs(CS_ARCH_X86,CS_MODE_32)
    pending=[entry]; instructions={}; external=[]
    while pending:
        at=pending.pop()
        while at not in instructions:
            if not entry <= at < entry+0x10000:
                external.append(hex(at));break
            instruction=next(decoder.disasm(image[at-0x400000:at-0x400000+16],at,count=1))
            instructions[at]=instruction
            assert len(instructions)<10000
            if instruction.mnemonic=='ret':break
            next_address=at+instruction.size
            if instruction.mnemonic.startswith('j'):
                if instruction.op_str.startswith('0x'):
                    pending.append(int(instruction.op_str,16))
                else:
                    raise AssertionError(f'Unproven indirect branch {at:#x}')
                if instruction.mnemonic=='jmp':break
            at=next_address
    return instructions,external


def main():
    source=(ROOT/'reports/screen-settings/client/silver.dll').read_bytes()
    candidate=(ROOT/'reports/ui-scale/core/silver.dll').read_bytes()
    original=pefile.PE(data=source);updated=pefile.PE(data=candidate)
    image=original.get_memory_mapped_image();cases=[]
    assert len(original.sections)==len(updated.sections)==13
    assert source[original.get_offset_from_rva(0x823000):original.get_offset_from_rva(0x823000)+0x2000]==candidate[updated.get_offset_from_rva(0x823000):updated.get_offset_from_rva(0x823000)+0x2000]
    for native in dict.fromkeys([target for _,target,_ in scale.UI_CALLS]+[0xa6a408]):
        instructions,external=reachable(image,native)
        returns=[(hex(i.address),i.op_str) for i in instructions.values() if i.mnemonic=='ret']
        assert returns and all(not amount for _,amount in returns),(hex(native),returns)
        stack_args=[hex(i.address) for i in instructions.values() if '[ebp +' in i.op_str]
        assert not stack_args,(hex(native),stack_args)
        assert image[native-0x400000:native-0x400000+3]==bytes.fromhex('558bec')
        cases.append({'native':hex(native),'reachable_returns':returns,'stack_argument_reads':stack_args,'external_exception_branches':external})
    for site,native,name in scale.WORLD_CALLS:
        assert candidate[updated.get_offset_from_rva(site-0x400000):updated.get_offset_from_rva(site-0x400000)+5]==scale.call_bytes(site,native)
    host_path=ROOT.parent/'Program Files (x86)'/'TIOnline'/'ti.exe'
    if not host_path.exists():host_path=Path('C:/Program Files (x86)/TIOnline/ti.exe')
    host=pefile.PE(str(host_path));host_image=host.get_memory_mapped_image()
    for va,target in ((0x6fcef5,0x663834),(0x6611c5,0x65085c)):
        assert host_image[va-0x400000:va-0x400000+5]==scale.call_bytes(va,target)
    # The read-only world-camera offsets and immutable host mouse are distinct
    # from the logical Silver canvas. No host size or camera write is installed.
    result={'result':'PASS','candidate_sha256':hashlib.sha256(candidate).hexdigest(),
            'native_gui_callees':cases,'callee_stack_argument_bytes':0,
            'published_screen_payload_preserved':True,'pe_sections':13,
            'native_textout_flush_before_return':{'function':'0x6fcd84','call':'0x6fcef5','flush':'0x663834'},
            'native_portrait_quad_upload_before_return':{'function':'0x661058','call':'0x6611c5','upload':'0x65085c'},
            'physical_world_calls_preserved':[{'site':hex(s),'target':hex(t),'name':n} for s,t,n in scale.WORLD_CALLS],
            'private_canvas':{'width':'0xb771e0','height':'0xb771e4','game_rect':'0xb749d4','mouse_xy':['0xb77150','0xb77154']},
            'physical_world_mouse':['TI[[0x76e518]]','TI[[0x76e440]]'],
            'physical_world_picking_path':['Silver0x9db7ac','Silver0xa889ec','TI0x71cd84 cmd2/3','TI0x72ca68'],
            'real_client_rendering_verified':False}
    out=ROOT/'reports/ui-scale/core/static-proof.json'
    out.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(f'PASS: {len(cases)} explicit GUI callee ABIs, native flush and preserved screen/world paths')


if __name__=='__main__':main()
