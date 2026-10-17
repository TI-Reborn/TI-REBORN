"""Original missing-HP sum and price multiplication, with human/dog/dead cases."""
from verify_auth_native import *
from tio.battle_recovery import CREDITS_PER_HP


def hospital_price(cases,tariff):
    """Execute Hospital painter's selection/HP/FPU arithmetic, skip graphics.

    Unlike the results helper this reads selected flag40, not ownership flag41.
    Stop just before the total is converted to the displayed price string.
    """
    u=emulator();table=DATA;params=DATA+0x1000;window=DATA+0x2000
    put32(u,0xac618c,table);put32(u,0xac5ac0,params)
    u.mem_write(params,struct.pack('<f',tariff));u.mem_map(0x30000000,0x30000)
    for i,(hp,maximum,selected) in enumerate(cases):
        actor=0x30000000+i*0x7000;put32(u,table+i*4,actor)
        u.mem_write(actor+0x40,bytes([selected]))
        u.mem_write(actor+0x6006,struct.pack('<HH',hp,maximum))
    result=[]
    def hook(uc,address,size,user):
        if address==0x8c8d95:
            # Skip background drawing CALL and its four callee-cleaned args.
            uc.reg_write(UC_X86_REG_ESP,uc.reg_read(UC_X86_REG_ESP)+16)
            uc.reg_write(UC_X86_REG_EIP,0x8c8d9a)
        elif address==0x8c8dc6:
            uc.reg_write(UC_X86_REG_EIP,0x8c8e59)  # skip name/HP text drawing
        elif address==0x8c8e84:
            result.append(get32(uc,uc.reg_read(UC_X86_REG_EBP)-8));uc.emu_stop()
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,window)
    u.emu_start(0x8c8d0c,STOP,count=5000)
    assert len(result)==1
    return result[0]


def main():
    u=emulator();table=DATA;params=DATA+0x1000
    put32(u,0xac618c,table);put32(u,0xac5ac0,params)
    u.mem_write(params,struct.pack('<f',CREDITS_PER_HP))
    cases=((1,105,True),(1,100,True),(0,100,True),(0,100,False))
    u.mem_map(0x30000000,0x20000)
    for i,(hp,maximum,own) in enumerate(cases):
        actor=0x30000000+i*0x7000
        put32(u,table+i*4,actor);put32(u,actor+0x28,i+1)
        u.mem_write(actor+0x41,bytes([own]))
        u.mem_write(actor+0x6006,struct.pack('<HH',hp,maximum))
    u.reg_write(UC_X86_REG_ESP,STACK+0x7000)
    # Stop before the price helper's final return; original FPU rounding runs.
    u.emu_start(0x8c8b30,0x8c8b4d,count=1000)
    price=u.reg_read(UC_X86_REG_EAX)
    assert price==(104+99+100)*CREDITS_PER_HP,price
    print('Original treatment price: PASS',price)
    cases=[([(100,126,True)],0,0),([(100,126,True)],CREDITS_PER_HP,52),
           ([(101,126,True)],CREDITS_PER_HP,50),
           ([(100,126,True),(50,100,True),(0,100,False)],CREDITS_PER_HP,152),
           ([(126,126,True)],CREDITS_PER_HP,0)]
    for actors,tariff,expected in cases:assert hospital_price(actors,tariff)==expected
    (ROOT/'evidence/hospital_price_native.json').write_text(json.dumps({'sha256':EXPECTED_SHA,
        'method':hospital_price.__doc__,'cases':cases,'status':'PASS'},indent=2)+'\n')
    print('Original Hospital displayed price: zero tariff regression,52/50credits,selection,total,healthy PASS')


if __name__=='__main__':main()
