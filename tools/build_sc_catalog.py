"""Build an explicitly provisional SC assortment from existing client items.

No original SC offer list or prices are present in the installed source CFG.
Selection is local policy, not an inference that cant_buy means premium.
Never rebuild the ordinary shop or the shared item XML from this tool.
"""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def main():
    source = ROOT / 'evidence/items_diagnostic_provenance.json'
    records = json.loads(source.read_text(encoding='utf-8'))['records']
    templates = {int(i.get('id')) for i in ET.parse(ROOT / 'evidence/items_diagnostic.xml').getroot()}
    offers = []
    for record in records:
        f = record['source_fields']
        item_id = int(record['id'])
        if (item_id not in templates or item_id >= 65000 or item_id in (0, 1, 2, 300, 333, 337)
                or f.get('freaks_only') == '1' or not f.get('image') or not f.get('durability')):
            continue
        # Source-defined special editions plus otherwise unavailable items.
        if not (f.get('cant_buy_in_private_store') == '1' or f.get('special') == '1'
                or f['name'].endswith(' SE') or item_id in (30, 263, 264)):
            continue
        gold = 25 if f.get('itype') in ('ammo', 'medkit') else 100
        offers.append(dict(lot_id=100000 + item_id, item_id=item_id, name=f['name'],
                           gold=gold, durability=int(f['durability']),
                           pack_count=int(f.get('packamount', '1')), stock_per_account=1000))
    offers.sort(key=lambda o: o['item_id'])
    config = dict(status='LOCAL_PROVISIONAL_NOT_ORIGINAL_SC_ASSORTMENT_OR_PRICES',
                  source='evidence/items_diagnostic_provenance.json',
                  source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                  policy='Base enhancement 0; Gold only; 25 Gold consumables, 100 other goods; stock 1000 per account.',
                  offers=offers)
    (ROOT / 'config/sc_catalog.json').write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Built {len(offers)} provisional SC offers')


if __name__ == '__main__':
    main()
