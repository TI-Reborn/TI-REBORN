"""Execute original7F/01 serializer and8c0790 model consumer.

Actor/skill lookup stubbed, original getters and model writes executed.
Stop before UI refresh; dispatcher and rendered cooldown are not tested.
"""
from verify_auth_native import *
from tio.protocol.ability_status import AbilityStatus, encode_ability_status


def run(state, remaining, slot):
    u = emulator()
    obj, row, flags, out = DATA, DATA+0x100, DATA+0x200, DATA+0x400
    put32(u, obj, 17); u.mem_write(obj+4, b'\x01')
    put32(u, obj+8, row); put32(u, obj+12, 1); put32(u, obj+16, flags)
    u.mem_write(flags, b'\x01')
    put32(u, row, 23); u.mem_write(row+4, bytes((1, 1, 1, state, 1)))
    put32(u, row+12, remaining); u.mem_write(row+16, b'\x01')
    put32(u, 0xacd0e0, out); put32(u, 0xacd0f0, 0)
    u.reg_write(UC_X86_REG_EAX, obj); u.emu_start(0x62f038, STOP, count=2000)
    assert u.reg_read(UC_X86_REG_EIP) == STOP
    packet = bytes(u.mem_read(out, get32(u, 0xacd0f0)))
    assert packet == encode_ability_status(17, [AbilityStatus(23, 1, state, remaining)])
    actor, skills = DATA+0x2000, DATA+0x9000
    put32(u, 0xac618c, DATA+0x1000); put32(u, DATA+0x1000, actor)
    put32(u, actor+0x304, skills)
    reached = []
    def hook(uc, address, size, user):
        if address in (0xa93f70, 0x9d5300):
            uc.reg_write(UC_X86_REG_EAX, 0 if address == 0xa93f70 else slot)
            return_from_stub(uc)
        elif address == 0x8c0aae:
            reached.append(True); uc.emu_stop()
    u.hook_add(UC_HOOK_CODE, hook)
    put32(u, STACK+0x8000, STOP); u.reg_write(UC_X86_REG_ESP, STACK+0x8000)
    u.reg_write(UC_X86_REG_EAX, obj); u.emu_start(0x8c0790, STOP, count=2000)
    record = skills + slot*0x348
    assert reached
    assert bytes(u.mem_read(record+0x31e, 1)) == b'\x01'
    assert bytes(u.mem_read(record+0x338, 1)) == bytes((state,))
    assert get32(u, record+0x328) == remaining
    return {'state': state, 'remaining': remaining, 'slot': slot, 'packet_hex': packet.hex()}


if __name__ == '__main__':
    cases = [run(3, 3, 0), run(3, 1, 2), run(4, 0, 0)]
    (ROOT/'evidence/ability_status_native.json').write_text(json.dumps({
        'sha256': EXPECTED_SHA, 'method': __doc__, 'cases': cases,
        'mappings': {'serializer': '62f038', 'consumer': '8c0790',
                     'level': '31e', 'state': '338', 'remaining': '328',
                     'cooldown_ui': '8ba31f', 'available_gate': '8bba8e'}}, indent=2)+'\n')
    print('Original skill status serializer/model:3 cases PASS')
