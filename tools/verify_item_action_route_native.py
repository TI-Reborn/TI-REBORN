"""Original997260 action routes to920068 and bypasses legacy6B block.

Managed initialization/cleanup and destination window isolated. Executes
original control flow to return; not proof of action label or window behavior.
"""
from verify_auth_native import *

if __name__=='__main__':
    u=emulator();calls=[]
    assert bytes(u.mem_read(0x91e8d2,len(b'TGUI_SupplementWindow')))==b'TGUI_SupplementWindow'
    put32(u,0xad0d88+0x28,1001)
    def hook(uc,address,size,user):
        if address in (0x40c8cc,0x40c9a4):return_from_stub(uc)
        elif address==0x920068:
            arg=uc.reg_read(UC_X86_REG_EAX)
            calls.append({'target':'0x920068','argument':hex(arg),'instance_id':get32(uc,arg+0x28)})
            return_from_stub(uc)
        elif address==0x992294:
            raise AssertionError('Legacy batch sender unexpectedly reached')
    u.hook_add(UC_HOOK_CODE,hook)
    u.emu_start(0x997260,STOP,count=1000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    assert calls==[{'target':'0x920068','argument':'0xad0d88','instance_id':1001}]
    result={'sha256':EXPECTED_SHA,'method':__doc__,'entry':'0x997260','calls':calls,
            'legacy_batch_called':False,'returned':True,
            'window_class':'TGUI_SupplementWindow','window_class_rtti':'0x91e8d2',
            'next_static_chain':'920068 copies item ->921118; validation9201a8, UI9217e8. Supplement window, not established equip action.'}
    (ROOT/'evidence/item_action_route_native.json').write_text(json.dumps(result,indent=2)+'\n')
    print('Original item action: new window route reached, legacy6B bypassed, return PASS')
