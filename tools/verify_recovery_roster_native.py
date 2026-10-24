"""Observe real native66 side effects and targeted4E HP writes, without a GUI.

Uses the explicitly requested player's read-only packet snapshots locally.
Allocation, equipment resource lookup and UI callbacks are isolated. The
selected native roster slot stays fixed while nonselected pets are updated.
"""
import json
from pathlib import Path
import sys
import struct

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT)]
from verify_auth_native import *
from unicorn.x86_const import *

REPORT=ROOT/'reports/recovery-roster-20261017'


def run(packet,human,identity):
    u=emulator();models=0x4000000;u.mem_map(models,0x40000)
    slots=DATA+0x4000;put32(u,0xac618c,slots)
    for index,actor_id in enumerate((1,2,3,4)):
        model=models+index*0x10000;put32(u,slots+4*index,model)
        put32(u,model+0x28,actor_id);put32(u,model+4,1)
    for index,address in enumerate((0xac64a0,0xac64b4,0xac55cc,0xac5fe4)):
        put32(u,address,DATA+0x5000+index*0x40)
    put32(u,DATA+0x5040,0) # Native selected slot: player1 throughout.
    # A real numeric UI cache updated by66 outside the selected-slot check.
    put32(u,0xac5840,DATA+0x5800);put32(u,DATA+0x5800,0x12345678)
    # Additional owner/profile cache indirections used by real saved packets.
    for index,address in enumerate((0xac5a98,0xac5498,0xac60d4,0xac599c,0xac640c,0xac5e78)):
        put32(u,address,DATA+0x5900+index*0x40)
    context=DATA+0x6000;u.mem_write(DATA,packet[1:]);calls=[]
    noops={0x40c8cc,0x40eca8,0xa853cc,0x40b47c,0x68a204,0x43afc0,
           0x68a774,0x43b31c,0xa7a13c,0x98f978,0xa855ac,0xa88a78,
           0xa86df8,0x8731cc,0x917484,0x6747dc,0x98fc48,0xa0f760}
    def hook(uc,a,n,_):
        if a==0x605f1c:
            target=uc.reg_read(UC_X86_REG_EAX);ptr=get32(uc,target)
            name=bytes(uc.mem_read(ptr,256)).split(b'\0',1)[0]
            put32(uc,target,ptr+len(name)+1);put32(uc,uc.reg_read(UC_X86_REG_EDX),0);return_from_stub(uc)
        elif a==0x4092ac:uc.reg_write(UC_X86_REG_EAX,context);return_from_stub(uc)
        elif a==0xa93f9c:uc.reg_write(UC_X86_REG_EAX,0 if human else 1);return_from_stub(uc)
        elif a==0xa84704:
            sp=uc.reg_read(UC_X86_REG_ESP);return_from_stub(uc);uc.reg_write(UC_X86_REG_ESP,sp+12)
        elif a in noops:calls.append(hex(a));return_from_stub(uc)
        elif a==0x8c4fb7:uc.emu_stop()
    u.hook_add(UC_HOOK_CODE,hook)
    u.reg_write(UC_X86_REG_EAX,DATA);u.reg_write(UC_X86_REG_EDX,len(packet)-1)
    u.emu_start(0x8c4380,STOP,count=50000)
    assert u.reg_read(UC_X86_REG_EIP)==0x8c4fb7
    assert get32(u,DATA+0x5040)==0
    model=models+(identity-1)*0x10000
    assert get32(u,model+0x28)==identity
    return dict(actor=identity,selected_slot=0,ui_cache_before=0x12345678,ui_cache_after=get32(u,DATA+0x5800),
                ui_refresh_calls=calls,health=int.from_bytes(u.mem_read(model+0x6006,2),'little'))


def main():
    data=json.loads(sorted(REPORT.glob('observation-*.json'))[-1].read_text())
    cases=[run(bytes.fromhex(p['projected_packet_hex']),p['human'],p['id']) for p in data['pets'] if p['id'] in (2,4)]
    assert all('0x98f978' in c['ui_refresh_calls'] and '0x8731cc' in c['ui_refresh_calls'] for c in cases)
    #4E native status4 writes only the requested model's HP up to the first UI
    #callback. The selected model, equipment and stat memory are canaries.
    hp=[]
    for identity in (2,4):
        u=emulator();actor=DATA+0x2000;other=DATA+0x9000;slots=DATA+0x100
        put32(u,0xac618c,slots);put32(u,slots,other);put32(u,slots+4,actor)
        canary=bytes((i*37+11)&255 for i in range(0x6100));u.mem_write(actor,canary)
        u.mem_write(other,b'\x6d'*0x6100);before=bytes(u.mem_read(other,0x6100))
        reached=[]
        def hook(uc,a,n,_):
            if a==0xa93f70:uc.reg_write(UC_X86_REG_EAX,1);return_from_stub(uc)
            elif a==0x8c75b9:reached.append(True);uc.emu_stop()
        u.hook_add(UC_HOOK_CODE,hook)
        u.reg_write(UC_X86_REG_EAX,identity);u.reg_write(UC_X86_REG_EDX,4);u.reg_write(UC_X86_REG_ECX,55)
        u.emu_start(0x8c7320,STOP,count=1000)
        expected=bytearray(canary);expected[0x6006:0x6008]=struct.pack('<H',55)
        assert reached and bytes(u.mem_read(actor,0x6100))==bytes(expected)
        assert bytes(u.mem_read(other,0x6100))==before
        hp.append(dict(actor=identity,only_current_hp_changed=True,other_actor_untouched=True))
    report=dict(passed=True,full_snapshots=cases,targeted_health=hp,graphical_clients=False,
                live_player_modified=False,limitations=__doc__)
    (REPORT/'native-diagnosis.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(dict(passed=True,full66_reapplies_equipment_and_refreshes_roster=True,
                         targeted4e_preserves_other_fields=True,graphical_clients=False)))


if __name__=='__main__':main()
