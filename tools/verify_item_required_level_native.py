"""Original required-level function A7C500, with synthetic template metadata.

No policy branches are stubbed. Cached template lookup, high-upgrade exception
and level comparisons execute from silver.dll. Ordinary type0 is outside the
two exceptional types23/24; this probe does not claim to run the XML loader.
"""
from verify_auth_native import *


def main():
    u=emulator(); item=DATA+0x1000; table=DATA+0x3000
    put32(u,0xac637c,DATA+0x2000); put32(u,DATA+0x2000,table)
    put32(u,table-4,1)  # Dynamic array length; cached item index0 is valid.
    put32(u,item+4,0); put32(u,item+8,252)
    rows=[]
    for base in (1,4,12):
        u.mem_write(table+0x689,bytes((base,)))
        for effective,real in [(n,0) for n in range(26)]+[(3,20),(10,25),(15,19)]:
            u.mem_write(item+0x4e,bytes((effective,))); put32(u,item+0x50,real)
            u.reg_write(UC_X86_REG_ESP,STACK+0x8000); put32(u,STACK+0x8000,STOP)
            u.reg_write(UC_X86_REG_EAX,item)
            u.emu_start(0xa7c500,STOP,count=2000)
            assert u.reg_read(UC_X86_REG_EIP)==STOP
            required=u.reg_read(UC_X86_REG_EAX)
            gate=1 if effective<=3 else 4 if effective<=10 else 7 if effective<=15 else 11
            expected=base if max(effective,real)>=20 else max(base,gate)
            assert required==expected,(effective,real,base,required,expected)
            rows.append(dict(base=base,effective=effective,real=real,required=required))
    report=dict(sha256=EXPECTED_SHA,method=__doc__,entry='0xa7c500',high_upgrade_predicate='0xa7b480',cases=rows)
    (ROOT/'evidence/item_required_level_native.json').write_text(json.dumps(report,indent=2)+'\n')
    print(f'Original item required-level function: {len(rows)} cases PASS (+10=4, +15=7, +20=base)')


if __name__=='__main__':main()
