"""Run the published client candidate's C6 turn and score code in Unicorn."""
import sys
from pathlib import Path

import pefile
from verify_auth_native import (DATA, STOP, STACK, UC_HOOK_CODE, Uc, UC_ARCH_X86,
                                UC_MODE_32, get32, put32, return_from_stub)
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EDX,
                               UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP)

from deploy.client_ranked_squads import build
from tio.control_points import ControlPoints
from tio.protocol.ranked import encode_scores, encode_turn


def execute(image: bytes, packet: bytes, *, turn: bool) -> tuple:
    u = Uc(UC_ARCH_X86, UC_MODE_32)
    for address, size in ((0, 0x1000), (0x400000, (len(image)+0xfff)&~0xfff),
                          (DATA, 0x10000), (STACK, 0x10000)):
        u.mem_map(address, size)
    u.mem_write(0x400000, image)
    u.mem_write(DATA, packet)
    u.reg_write(UC_X86_REG_ESP, STACK+0x8000)
    put32(u, STACK+0x8000, STOP)
    actors = tuple(DATA+0x1000+i*0x1000 for i in range(5))
    put32(u, 0xac618c, DATA+0x100)
    for index, actor in enumerate(actors):
        put32(u, DATA+0x100+4*index, actor)
        put32(u, actor+0x28, 101+index)
        put32(u, actor+0x2c, 1 if index<4 else 268435458)
        u.mem_write(actor+0x41, b'\1')
    selected = []

    def hook(uc, address, _size, _user):
        if address == 0xa86888:
            uc.reg_write(UC_X86_REG_EAX, 1)
            return_from_stub(uc)
        elif address in (0x9cfa38, 0x43afc0, 0x43b1dc, 0xa88a78):
            return_from_stub(uc)
        elif address == 0x953a02:
            selected.append(get32(uc, get32(uc, uc.reg_read(UC_X86_REG_ESI))+0x28))
        elif address in (0x953a6d, 0x953ac1):
            uc.emu_stop()
        elif address == 0x68a850:
            raise AssertionError('Numeric score update was queued instead of applied')

    u.hook_add(UC_HOOK_CODE, hook)
    u.reg_write(UC_X86_REG_EAX, DATA+2 if turn else packet[0])
    u.reg_write(UC_X86_REG_EDX, DATA+1)
    u.reg_write(UC_X86_REG_ECX, len(packet))
    try:
        u.emu_start(0x953884 if turn else 0x9545e0, STOP, count=20000)
    except Exception as error:
        raise RuntimeError(f'Native execution stopped at {u.reg_read(UC_X86_REG_EIP):#x}') from error
    if turn:
        return tuple(u.mem_read(a+0x1f,1)[0] for a in actors), tuple(selected)
    assert u.reg_read(UC_X86_REG_EIP) == STOP
    return tuple(get32(u, a) for a in (0xad04b0,0xad04b4,0xad052c,0xad0530))


def main(path: Path) -> None:
    raw, _ = build(path.read_bytes())
    image = pefile.PE(data=raw).get_memory_mapped_image()
    assert execute(image, encode_turn(0, 1, 102, squad=True), turn=True) == ((0,0,0,0,1),(102,))
    assert execute(image, encode_turn(0, 1, 102), turn=True) == ((1,0,1,1,1),(102,))
    assert execute(image, encode_turn(1, 268435458, 105, squad=True), turn=True) == ((1,1,1,1,0),(105,))
    points = ControlPoints(((4,6),(20,25),(15,15)), [0,1,0], [45,20])
    assert execute(image, encode_scores(points), turn=False) == (45,10,20,5)
    print('Native TrueSkill squad locking, lead selection and score dispatch: PASS')


if __name__ == '__main__':
    main(Path(sys.argv[1]))
