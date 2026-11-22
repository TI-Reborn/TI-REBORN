"""Keep native service slots stable in the Shooting Range and hide contract buttons in mines."""
import argparse
import json
from pathlib import Path

from .client_contracts_windows import Code, absolute_load, mov
from tio.locations import MINE_LOCATIONS

IMAGE_BASE = 0x400000
TOWN = 0xAC5D58
RANGE = 17
STOCK_LAYOUT = 0x8588C0
STOCK_PROLOGUE = '558bec5153'
RANGE_LAYOUT, STOCK_ENTRY, CONTRACTS_ENTRY = 0x900, 0xA00, 0xB00
MINE_VISIBILITY = 0xC00
SLOTS = ((0xACF040, 0x20), (0xACF02C, 0x40), (0xACF058, 0x60), (0xACF044, 0x80))


def branch_outside_range(code: Code, label: str) -> None:
    absolute_load(code, TOWN)
    code.emit('85c0'); code.branch('0f84', label)
    code.emit('8338'); code.emit(f'{RANGE:02x}'); code.branch('0f85', label)


def patch_plan(plan: dict) -> None:
    """Extend the active contracts plan, retaining its existing widgets and hooks."""
    blocks = {block['offset']: block for block in plan['blocks']}
    if plan['count'] != 58 or any(start in blocks for start in
                                  (RANGE_LAYOUT, STOCK_ENTRY, CONTRACTS_ENTRY, MINE_VISIBILITY)):
        raise ValueError('Expected the current launcher contracts plan')
    header, records, stride = (plan[key] for key in ('header', 'records', 'stride'))

    def hide_contract_buttons(code: Code) -> None:
        for index in (0, 1):
            code.emit('a1'); code.alloc(records + index * stride)
            code.emit('85c0'); code.branch('0f84', f'no_extra{index}')
            code.emit('66c740490000')  # Native visibility and enabled flags.
            code.label(f'no_extra{index}')

    layout = Code(RANGE_LAYOUT)
    layout.emit('9c60')
    hide_contract_buttons(layout)
    for control, y in SLOTS:
        absolute_load(layout, control)
        layout.emit('85c0'); layout.branch('0f84', f'no_slot{y}')
        layout.emit('c74034'); layout.word(y)
        layout.label(f'no_slot{y}')
    layout.emit('a1'); layout.alloc(header + 24)
    layout.emit('85c0'); layout.branch('0f84', 'done')
    layout.emit('c7403cb0000000')
    layout.label('done'); layout.emit('619dc3')

    mine = Code(MINE_VISIBILITY)
    absolute_load(mine, TOWN)
    mine.emit('85c0'); mine.branch('0f84', 'done'); mine.emit('8b00')
    for town in MINE_LOCATIONS:
        mine.emit('3d'); mine.word(town); mine.branch('0f84', 'hide')
    mine.branch('e9', 'done')
    mine.label('hide'); hide_contract_buttons(mine)
    mine.label('done'); mine.emit('c3')
    blocks[mine.offset] = mine.finish()

    # Both native refresh paths can place the same controls in different orders.
    for entry in (STOCK_ENTRY, CONTRACTS_ENTRY):
        code = Code(entry)
        code.emit('9c60'); branch_outside_range(code, 'original')
        code.emit('619d'); code.local(RANGE_LAYOUT); code.emit('c3')
        code.label('original'); code.emit('619d')
        if entry == STOCK_ENTRY:
            code.emit(STOCK_PROLOGUE); code.jump(STOCK_LAYOUT + 5)
        else:
            code.emit('e9'); code.pointer('allocation', 0x400, True)
        blocks[entry] = code.finish()

    for offset in (0, 0x700):
        (call,) = (fix for fix in blocks[offset]['relocations']
                   if fix['kind'] == 'allocation' and fix['relative'] and fix['offset'] == 0x400)
        call['offset'] = CONTRACTS_ENTRY

    tick = Code(0x800)
    tick.emit('9c60833d'); tick.alloc(header + 24); tick.emit('00'); tick.branch('0f84', 'done')
    tick.emit('a1'); tick.alloc(records + 2 * stride)
    tick.emit('85c0'); tick.branch('0f85', 'existing'); tick.local(0x1000)
    tick.label('existing'); tick.emit('833d'); tick.alloc(header); tick.emit('01')
    tick.branch('0f85', 'visibility'); tick.local(0x5000)
    tick.local(MINE_VISIBILITY)  # Caption refresh reapplies both controls' flags.
    tick.label('visibility'); branch_outside_range(tick, 'open')
    tick.local(RANGE_LAYOUT)  # The periodic update writes visibility again.
    mov(tick, header + 8, 0)
    tick.emit('a1'); tick.alloc(records + 2 * stride)
    tick.emit('85c0'); tick.branch('0f84', 'done')
    tick.emit('80784900'); tick.branch('0f84', 'done')
    tick.emit('31d28b08ff11'); tick.branch('e9', 'done')
    tick.label('open'); tick.emit('a1'); tick.alloc(header + 8)
    tick.emit('85c0'); tick.branch('0f84', 'done'); tick.emit('50')
    mov(tick, header + 8, 0)
    tick.emit('a1'); tick.alloc(records + 2 * stride)
    tick.emit('5a83fa010f94c28b08ff11')
    tick.label('done'); tick.emit('619d558bec5356'); tick.jump(0xA3F301)

    blocks[tick.offset] = tick.finish()
    blocks[layout.offset] = layout.finish()
    ordered = sorted(blocks.values(), key=lambda block: block['offset'])
    for block, following in zip(ordered, ordered[1:]):
        if block['offset'] + len(block['hex']) // 2 > following['offset']:
            raise ValueError('Native location menu blocks overlap')
    plan['blocks'] = ordered
    plan['hooks'].append(dict(rva=STOCK_LAYOUT - IMAGE_BASE, before=STOCK_PROLOGUE,
                              target=STOCK_ENTRY, opcode=0xe9))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    plan = json.loads(args.source.read_bytes())
    patch_plan(plan)
    args.output.write_text(json.dumps(plan, indent=2) + '\n', encoding='utf-8')
