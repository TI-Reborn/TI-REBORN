"""Execute original B1/01 reader and B1/03 dispatcher, stubbing UI only."""
from verify_auth_native import *
from verify_city_catalogs_native import run_case
from tio.services import status, catalog
from tio.wallets import WalletStore
import tempfile


def paid(service, level):
    packet = status(service, level)
    u = emulator()
    u.mem_write(DATA, packet)
    captured = []
    consumed = []
    def hook(uc, addr, size, user):
        if addr == 0x847414:
            sp = uc.reg_read(UC_X86_REG_ESP)
            captured.append((uc.reg_read(UC_X86_REG_EAX), uc.reg_read(UC_X86_REG_EDX),
                             uc.reg_read(UC_X86_REG_ECX), get32(uc, sp+4), get32(uc, sp+8)))
            return_from_stub(uc)
            uc.reg_write(UC_X86_REG_ESP, uc.reg_read(UC_X86_REG_ESP)+8)
        elif addr == 0x84e317:
            consumed.append(get32(uc, uc.reg_read(UC_X86_REG_EBP)-4)-DATA)
    u.hook_add(UC_HOOK_CODE, hook)
    u.reg_write(UC_X86_REG_EAX, DATA+2)
    u.emu_start(0x84e280, STOP, count=10000)
    assert u.reg_read(UC_X86_REG_EIP) == STOP
    assert consumed == [len(packet)], consumed
    assert captured == [(service, 1, level, 0, 0)], captured
    return {'service': service, 'level': level, 'consumed': consumed[0]}


if __name__ == '__main__':
    results = [paid(s, n) for s in (1, 2) for n in (1, 2)]
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder)/'test.sqlite3'
        WalletStore(path).ensure('alice')
        run_case('services', catalog(path, 'alice'))
    output = {'dll_sha256': EXPECTED_SHA, 'paid_status': results, 'catalog_reader': 'passed',
              'scope': 'Original numeric parsers; paid-list UI insertion stubbed. Not graphical client validation.'}
    (ROOT/'evidence/services_native.json').write_text(json.dumps(output, indent=2), encoding='utf-8')
    print(json.dumps(output))
