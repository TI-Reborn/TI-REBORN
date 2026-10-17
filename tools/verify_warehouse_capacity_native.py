"""Verify native warehouse default and private-window capacity selection.

Execute original initializer stores and private-kind selection. Managed string
assignment is isolated; this verifies the number supplied to the UI, not pixels.
"""
from verify_auth_native import *
from unicorn.x86_const import UC_X86_REG_EBX, UC_X86_REG_EBP


def run():
    u = emulator()
    settings = 0xad27a4
    u.reg_write(UC_X86_REG_EBX, settings)
    u.emu_start(0x9dc861, 0x9dc8d6, count=100)
    default = int.from_bytes(u.mem_read(settings + 0xe, 2), 'little')
    assert default == 3000, default
    configured = json.loads((ROOT / 'config/city_catalogs.json').read_text(encoding='utf-8'))['warehouse_capacity']
    assert configured == default, (configured, default)
    put32(u, 0xac6008, settings)
    frame = DATA + 0x8000
    u.reg_write(UC_X86_REG_EBP, frame)

    def hook(uc, address, size, user):
        if address == 0x40b4c4:  # Managed caption assignment, not capacity logic.
            return_from_stub(uc)

    u.hook_add(UC_HOOK_CODE, hook)
    cases = []
    for capacity in (default, 17):
        u.mem_write(settings + 0xe, capacity.to_bytes(2, 'little'))
        u.reg_write(UC_X86_REG_EBX, 0)  # Private warehouse kind.
        u.emu_start(0x9b3671, 0x9b36ad, count=100)
        observed = get32(u, frame - 0x14)
        assert observed == capacity, observed
        assert get32(u, frame - 0x10) == 3  # Private warehouse widget.
        cases.append(dict(capacity=capacity, selected_capacity=observed, widget_type=3))
    return dict(default_capacity=default, configured_capacity=configured, cases=cases)


if __name__ == '__main__':
    result = dict(sha256=EXPECTED_SHA, method=__doc__, **run())
    (ROOT / 'evidence/warehouse_capacity_native.json').write_text(
        json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print('Original warehouse default and private UI capacity: PASS')
