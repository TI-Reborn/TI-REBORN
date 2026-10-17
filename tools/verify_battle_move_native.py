"""Original ti.exe6dc600 reader/path loop and final coordinate writes.

Actor lookup, animation/UI calls isolated; final notification block skipped.
Execution stops at6dc9f8 after path processing, before managed cleanup.
"""
from verify_battle_loaded_native import *
from tio.protocol.battle_move import BattleMove, encode_battle_move


def run(path):
    u = exe_emulator()
    actor, context = DATA+0x2000, DATA+0x3000
    put32(u, 0x76e430, DATA+0x1000)
    put32(u, DATA+0x1000, actor)
    put32(u, 0x76e17c, DATA+0x1100)
    put32(u, DATA+0x1100, context)
    put32(u, actor+0x1cc, 2)
    put32(u, actor+0x1d0, 3)
    packet = encode_battle_move(BattleMove(17, tuple(path)))
    u.mem_write(DATA, packet[1:])
    consumed = []

    def hook(uc, address, size, user):
        if address == 0x7189b4:
            assert uc.reg_read(UC_X86_REG_EAX) == 17
            uc.reg_write(UC_X86_REG_EAX, 0)
            return_from_stub(uc)
        elif address in (0x70d704, 0x72651c, 0x723fa4):
            uc.reg_write(UC_X86_REG_EAX, 0)
            return_from_stub(uc)
        elif address == 0x6dc920:
            uc.reg_write(UC_X86_REG_EIP, 0x6dc9b8)
        elif address == 0x6f68a8:
            sp = uc.reg_read(UC_X86_REG_ESP)
            return_from_stub(uc)
            uc.reg_write(UC_X86_REG_ESP, sp+8)
        elif address == 0x6dc9f8:
            consumed.append(get32(uc, uc.reg_read(UC_X86_REG_EBP)-4)-DATA)
            uc.emu_stop()

    u.hook_add(UC_HOOK_CODE, hook)
    u.reg_write(UC_X86_REG_EAX, DATA)
    u.emu_start(0x6dc600, STOP, count=5000)
    assert consumed == [len(packet)-1], consumed
    final = (get32(u, actor+0x1cc), get32(u, actor+0x1d0))
    assert final == (tuple(path[-1]) if path else (2,3)), final
    return dict(packet_hex=packet.hex(), path=path, final_position=final, consumed=consumed[0])


if __name__ == '__main__':
    cases = [run([]), run([(4,5)]), run([(3,3),(4,3),(4,4)]), run([(0,255)])]
    (ROOT/'evidence/battle_move_native.json').write_text(json.dumps(
        dict(sha256=EXE_SHA, method=__doc__, cases=cases,
             dispatch='6dd34c opcode3D ->6dd3ad ->queued6dc600'),indent=2)+'\n',encoding='utf-8')
    print('Original BattleSoldierMove reader: 4 cases PASS')
