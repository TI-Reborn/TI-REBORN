"""Execute the native button binding and packet writer; transport is stubbed."""
import argparse
from pathlib import Path

import pefile
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EIP, UC_X86_REG_ESP

from verify_auth_native import DATA, STACK, STOP, get32, put32, return_from_stub
from deploy.client_main_menu import BUTTON_CALLBACK, ENTRY, IMAGE_BASE
from tio.protocol.character_select import RETURN_TO_CHARACTER_SELECT


def verify(raw: bytes, base: int) -> None:
    delta = base - IMAGE_BASE
    with pefile.PE(data=raw) as pe:
        pe.relocate_image(base)
        image = pe.get_memory_mapped_image()
    u = Uc(UC_ARCH_X86, UC_MODE_32)
    for start, size in ((base, (len(image) + 0xfff) & ~0xfff),
                        (DATA, 0x10000), (STACK, 0x10000)):
        u.mem_map(start, size)
    u.mem_write(base, image)
    callback = get32(u, BUTTON_CALLBACK + delta)
    assert callback == ENTRY + delta, 'Main menu still calls the legacy disconnect'
    obj, handle, table, flush = DATA, DATA + 0x2000, DATA + 0x3000, DATA + 0x4000
    put32(u, 0xac600c + delta, handle)
    put32(u, handle, obj)
    put32(u, obj, table)
    put32(u, table, flush)
    put32(u, STACK + 0x8000, STOP)
    u.reg_write(UC_X86_REG_ESP, STACK + 0x8000)
    sent = []

    def hook(uc: Uc, address: int, _size: int, _user: object) -> None:
        if address == 0x6748b0 + delta:
            uc.reg_write(UC_X86_REG_EAX, handle)
            return_from_stub(uc)
        elif address == flush:
            sent.append(bytes(uc.mem_read(obj + 4, get32(uc, obj + 0x1004))))
            return_from_stub(uc)

    u.hook_add(UC_HOOK_CODE, hook)
    u.emu_start(callback, STOP, count=2000)
    assert u.reg_read(UC_X86_REG_EIP) == STOP
    assert sent == [RETURN_TO_CHARACTER_SELECT], sent


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('silver', type=Path)
    raw = parser.parse_args().silver.read_bytes()
    for base in (0x400000, 0x12000000):
        verify(raw, base)
    print('Main menu binding sent one character list request at both image bases')
