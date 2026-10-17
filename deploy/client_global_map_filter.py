"""Map-only GPU mip generation and reversible native sampler state.

PNG files and their level-zero dimensions/UVs remain untouched. The native
loader calls D3DX on its own initialization thread; only its 22 checked object
loads receive a full BOX-filtered mip chain. A temporary IAT pointer is restored
on success, ordinary failed loads, and SEH search/unwind. Drawing uses the
engine's own sampler cache/setters on its render thread, then restores all
three prior stage-zero filters. MapRect_2 submits DrawPrimitive synchronously.
"""
from __future__ import annotations

from .client_equipment_batch import Code

LOAD_OFFSET = 0x16000
SHIM_OFFSET = 0x16400
CLEAN_OFFSET = 0x16600
EXCEPTION_OFFSET = 0x16800
BEGIN_OFFSET = 0x16a00
END_OFFSET = 0x16c00
STATE_OFFSET = 0x17000

TI_BASE, IAT_OLD, IAT_SLOT, PROTECT, ACTIVE, THREAD, MIP_CALLS = range(0, 28, 4)
SAMPLER, OLD_MAG, OLD_MIN, OLD_MIP, DRAW_ACTIVE, SCOPES = range(28, 52, 4)
RESTORES, PROTECT_FAILURES = 52, 56
TI_IMAGE_LOAD_RVA = 0x31c73c
TI_D3DX_IAT_RVA = 0x389644
TI_D3DX_STUB_RVA = 0x1f585c
TI_D3DX_RETURN_RVA = 0x21081d
TI_RENDERER_RVA = 0x36de0c
TI_MAG_RVA, TI_MIN_RVA, TI_MIP_RVA = 0x25a934, 0x25aa00, 0x25aad0
VP_RVA, THREAD_RVA = 0x77a090, 0x77a1a4


def address(a, offset): return a.DRAW + offset


def field(c, a, op, offset):
    c.emit(op); c.word(a.REGION + STATE_OFFSET + offset)


def set_field(c, a, offset, value):
    field(c, a, 'c783', offset); c.word(value)


def native(c, a, rva):
    field(c, a, '8b83', TI_BASE); c.emit('05'); c.word(rva); c.emit('ffd0')


def load_code(a):
    c = Code(address(a, LOAD_OFFSET)); c.emit('9c60'); c.base()
    # The exact registered Image1 callback identifies the already loaded TI.
    a.global_pointer(c, 0xac5d5c); c.emit('85c0'); c.branch('0f84', 'stock')
    c.emit('8b00 85c0'); c.branch('0f84', 'stock')
    c.emit('2d'); c.word(TI_IMAGE_LOAD_RVA)
    # Current pinned main executable is loaded at its preferred base.
    c.emit('3d00004000'); c.branch('0f85', 'stock')
    field(c, a, '8983', TI_BASE)
    c.emit('6681b8'); c.word(TI_D3DX_STUB_RVA); c.emit('ff25')
    c.branch('0f85', 'stock')
    c.emit('8b90'); c.word(TI_D3DX_STUB_RVA + 2)
    c.emit('8db0'); c.word(TI_D3DX_IAT_RVA); c.emit('39f2')
    c.branch('0f85', 'stock')
    field(c, a, '89b3', IAT_SLOT)
    field(c, a, '83bb', ACTIVE); c.emit('00'); c.branch('0f85', 'stock')
    c.emit('8b06 85c0'); c.branch('0f84', 'stock')
    field(c, a, '8983', IAT_OLD)
    c.emit('8d83'); c.word(a.REGION + STATE_OFFSET + PROTECT)
    c.emit('50 6a04 6a04 56 ff93'); c.word(VP_RVA)
    c.emit('85c0'); c.branch('0f84', 'protect_failed')
    c.emit('ff93'); c.word(THREAD_RVA); field(c, a, '8983', THREAD)
    c.emit('8d83'); c.word(a.REGION + SHIM_OFFSET); c.emit('8906')
    set_field(c, a, ACTIVE, 1); field(c, a, 'ff83', SCOPES)
    # Ordinary loader failure returns normally. A generic SEH search handler
    # performs the same cleanup if the loader propagates an exception.
    c.emit('8d83'); c.word(a.REGION + EXCEPTION_OFFSET)
    c.emit('50 64ff3500000000 64892500000000')
    c.emit('8b442424 8b54241c 8b4c2420'); c.call(0x4f2c50)
    c.emit('5a 83c404 64891500000000')
    c.call(address(a, CLEAN_OFFSET)); c.emit('619d c3')
    c.label('protect_failed'); field(c, a, 'ff83', PROTECT_FAILURES)
    c.label('stock')
    c.emit('8b44241c 8b542414 8b4c2418'); c.call(0x4f2c50)
    c.emit('619d c3')
    return c.finish(0x400)


def shim_code(a):
    c = Code(address(a, SHIM_OFFSET)); c.emit('9c60'); c.base()
    field(c, a, '83bb', ACTIVE); c.emit('01'); c.branch('0f85', 'stock')
    field(c, a, '8b83', TI_BASE); c.emit('05'); c.word(TI_D3DX_RETURN_RVA)
    c.emit('3b442424'); c.branch('0f85', 'stock')
    c.emit('ff93'); c.word(THREAD_RVA)
    field(c, a, '3b83', THREAD); c.branch('0f85', 'stock')
    # D3DX stdcall args: MipLevels +24; Filter +40; MipFilter +44.
    # pushfd/pushad add 36. Leave Filter NONE=1 and all other args exact.
    c.emit('c744243c00000000 c744245005000000')
    field(c, a, 'ff83', MIP_CALLS)
    c.label('stock')
    field(c, a, '8b83', IAT_OLD)
    # pushad's unused saved-ESP slot survives popad as a tail-jump target.
    c.emit('8944240c 619d ff6424e8')
    return c.finish(0x200)


def cleanup_code(a):
    c = Code(address(a, CLEAN_OFFSET)); c.emit('9c60'); c.base()
    field(c, a, '83bb', ACTIVE); c.emit('01'); c.branch('0f85', 'done')
    set_field(c, a, ACTIVE, 0)
    field(c, a, '8bb3', IAT_SLOT)
    c.emit('8d83'); c.word(a.REGION + SHIM_OFFSET)
    c.emit('3906'); c.branch('0f85', 'protection')
    field(c, a, '8b83', IAT_OLD); c.emit('8906')
    c.label('protection')
    # Restore the original page protection without overwriting its saved value.
    c.emit('83ec04 54'); field(c, a, 'ffb3', PROTECT)
    c.emit('6a04 56 ff93'); c.word(VP_RVA); c.emit('83c404')
    field(c, a, 'ff83', RESTORES)
    c.label('done'); c.emit('619d c3')
    return c.finish(0x200)


def exception_code(a):
    c = Code(address(a, EXCEPTION_OFFSET)); c.emit('9c60'); c.base()
    c.call(address(a, CLEAN_OFFSET)); c.emit('619d b801000000 c3')
    # EXCEPTION_DISPOSITION ExceptionContinueSearch = 1. cdecl, original
    # native exception semantics continue after reversing our temporary state.
    return c.finish(0x100)


def begin_code(a):
    c = Code(address(a, BEGIN_OFFSET)); c.emit('9c60'); c.base()
    field(c, a, '83bb', TI_BASE); c.emit('00'); c.branch('0f84', 'done')
    field(c, a, '83bb', DRAW_ACTIVE); c.emit('00'); c.branch('0f85', 'done')
    field(c, a, '8b83', TI_BASE); c.emit('8b80'); c.word(TI_RENDERER_RVA)
    c.emit('85c0'); c.branch('0f84', 'done')
    c.emit('8b00 85c0'); c.branch('0f84', 'done')
    c.emit('8b8048020000 85c0'); c.branch('0f84', 'done')
    c.emit('8b400c 85c0'); c.branch('0f84', 'done')
    field(c, a, '8983', SAMPLER)
    for cached, saved in ((0x68, OLD_MAG), (0x88, OLD_MIN), (0xa8, OLD_MIP)):
        c.emit('8b90'); c.word(cached); field(c, a, '8993', saved)
    set_field(c, a, DRAW_ACTIVE, 1)
    for setter in (TI_MAG_RVA, TI_MIN_RVA, TI_MIP_RVA):
        field(c, a, '8b83', SAMPLER); c.emit('31d2 b902000000 50')
        field(c, a, '8b83', TI_BASE); c.emit('05'); c.word(setter)
        c.emit('89c7 58 ffd7')
    c.label('done'); c.emit('619d c3')
    return c.finish(0x200)


def end_code(a):
    c = Code(address(a, END_OFFSET)); c.emit('9c60'); c.base()
    field(c, a, '83bb', DRAW_ACTIVE); c.emit('01'); c.branch('0f85', 'done')
    set_field(c, a, DRAW_ACTIVE, 0)
    for setter, saved in ((TI_MAG_RVA, OLD_MAG), (TI_MIN_RVA, OLD_MIN), (TI_MIP_RVA, OLD_MIP)):
        field(c, a, '8b83', SAMPLER); c.emit('31d2'); field(c, a, '8b8b', saved)
        c.emit('50'); field(c, a, '8b83', TI_BASE); c.emit('05'); c.word(setter)
        c.emit('89c7 58 ffd7')
    c.label('done'); c.emit('619d c3')
    return c.finish(0x200)


def extra_entries(a):
    return tuple((address(a, off), fn(a)) for off, fn in
                 ((LOAD_OFFSET, load_code), (SHIM_OFFSET, shim_code),
                  (CLEAN_OFFSET, cleanup_code), (EXCEPTION_OFFSET, exception_code),
                  (BEGIN_OFFSET, begin_code), (END_OFFSET, end_code)))


def metadata(a):
    return {'state_rva': a.REGION + STATE_OFFSET, 'state_fields': {
        'ti_base': TI_BASE, 'scope_active': ACTIVE, 'mip_calls': MIP_CALLS,
        'load_scopes': SCOPES, 'iat_restores': RESTORES, 'sampler_active': DRAW_ACTIVE,
        'protect_failures': PROTECT_FAILURES},
        'object_mip_levels': 0, 'object_mip_filter': 5, 'level_zero_filter': 1,
        'terrain_uses_original_loader': True,
        'sampler': 'Native stage 0 MAG/MIN/MIP LINEAR=2; all three cached states restored',
        'scope': '22 object loads only; exact Image1 callback, D3DX caller and thread guards',
        'exception_cleanup': 'SEH ContinueSearch restores original IAT pointer and protection',
        'draw_submission': 'MapRect_2 issues synchronous D3D DrawPrimitive before returning'}
