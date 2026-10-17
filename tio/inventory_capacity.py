"""One carried-item limit, after stacking, with safe legacy bag reduction."""
import json
from pathlib import Path

INVENTORY_SLOTS=json.loads((Path(__file__).resolve().parents[1]/'config/battle_loot.json').read_text())['inventory_slots']
if type(INVENTORY_SLOTS) is not int or not 1<=INVENTORY_SLOTS<=255:
    raise ValueError('Invalid inventory capacity')


def validate_capacity(before,after,*,limit=INVENTORY_SLOTS,error=ValueError):
    # Preserve existing oversized saves; do not allow their size to grow.
    # Count item records after compatible stacks have been merged.
    if len(after)>max(len(before),limit):raise error('Inventory is full')
