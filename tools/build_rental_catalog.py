"""Populate all rental-eligible client equipment; retain approved Gold prices."""
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tio.enhancement import EnhancementRules
from tio.rental import eligible_rental_items


def main():
    path=ROOT/'config/rental_catalog.json'
    data=json.loads(path.read_text(encoding='utf-8'))
    data['description']='All eligible equipment from the installed client catalog; manual rental levels/durations. Provisional user-approved Gold prices, not historical prices.'
    data['items']=sorted(eligible_rental_items(EnhancementRules()))
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f"Rental equipment: {len(data['items'])} templates, {len(data['items'])*12} offers")


if __name__=='__main__':main()
