"""Rebuild ordinary/Premium shop prices from the 2008-2011 manual tables.

Only catalog configuration is written; hosted accounts are never inputs/outputs.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# template: credits per pack, gold per pack (None means not sold for that currency)
PRICES = {
    3:(50,None),4:(54,None),5:(40,None),6:(36,None),7:(50,None),
    9:(55,1),10:(150,1),11:(300,2),12:(48,None),13:(60,None),15:(15,None),
    17:(450,None),18:(None,5),19:(None,10),24:(None,10),30:(1050,7),
    32:(None,None),36:(40,None),37:(60,None),
    210:(800,None),211:(400,None),212:(750,None),213:(450,None),214:(930,None),215:(850,None),
    216:(320,None),217:(700,None),218:(700,None),219:(450,None),220:(800,None),221:(800,None),
    229:(500,None),230:(250,None),231:(850,None),232:(750,None),233:(360,None),234:(1070,None),
    239:(450,None),240:(900,None),241:(900,None),242:(1350,9),243:(1800,12),244:(1200,8),
    245:(600,4),246:(1650,11),247:(1050,7),248:(None,55),249:(None,25),250:(None,45),
    251:(None,90),252:(None,126),253:(None,66),254:(7500,None),255:(1200,None),256:(None,150),
    258:(1200,8),259:(1050,7),260:(2550,17),261:(2200,15),262:(1200,8),
    263:(6000,None),264:(None,175),265:(2100,None),266:(None,70),
    301:(150,1),302:(600,4),303:(450,3),304:(900,6),305:(300,2),306:(750,5),
    307:(750,5),308:(750,5),309:(600,4),310:(750,5),311:(1050,7),312:(1200,8),313:(1200,8),
    317:(300,2),320:(150,1),326:(None,4),327:(150,1),329:(150,1),330:(750,5),
    331:(150,1),332:(300,2),334:(1800,12),335:(1350,9),336:(1050,7),338:(1500,10),
    339:(1350,9),340:(300,2),341:(1200,8),
}

def main():
    path = ROOT/'config/city_catalogs.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    # Original fixtures retained as provenance, so rebuilding is deterministic.
    archive = ROOT/'evidence/shop_catalog_before_original_prices.json'
    if not archive.exists():
        archive.write_text(path.read_text(encoding='utf-8'), encoding='utf-8')
    original = json.loads(archive.read_text(encoding='utf-8'))
    rows = original['item_categories']['0']
    names = {r['id']:r['name'] for r in json.loads((ROOT/'evidence/shop_catalog_provenance.json').read_text())['offers']}
    assert {r['item_id'] for r in rows} == set(PRICES), 'Every existing item needs an explicit source price/status'
    credits, gold, provenance = [], [], []
    for row in rows:
        item = row['item_id']; cr, au = PRICES[item]
        pack = row['unknown_u32_02']
        # Manual p77: nailgun ammunition is sold in boxes of 30, not legacy CFG 20.
        if item == 37: pack = 30
        if cr is not None:
            credits.append({**row,'unknown_u32_03':cr,'unknown_u32_02':pack})
        if au is not None:
            gold.append({'offer_id':1000+item,'item_id':item,'pack_count':3 if item==9 else pack,
                         'gold':au,'durability':row['durability']})
        section = 'ammunition' if item < 200 else 'armor' if item < 300 else 'weapons'
        provenance.append({'item_id':item,'name':names[item],'credits':cr,'gold':au,
                           'credit_pack':pack if cr else None,'gold_pack':(3 if item==9 else pack) if au else None,
                           'source_section':section,'status':'not_sold' if cr is None and au is None else 'documented'})
    data['item_categories']={'0':credits}
    data['premium_items']=gold
    data['price_revision']=20260925
    data['policy']='Documented original shop prices; see config/original_shop_prices.json. No synthetic currency conversion.'
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    report={'source':'https://ti.ggeek.ru/files/TIO_manual.pdf','era':'2008-2011 manual, not later SC sale prices',
            'mirrors':{'weapons':'https://aurols.ucoz.ua/index/vooruzhenie/0-19',
                       'armor':'https://aurols.ucoz.ua/index/obmundrovanie/0-18',
                       'ammunition':'https://aurols.ucoz.ua/index/amunicija/0-17'},
            'notes':['Null is unavailable in that currency, not zero/free.',
                     'Bandages: 55 credits each; 1 gold buys THREE.',
                     'Dog Meat is not sold. Existing owned items are preserved.',
                     'Freak Heavy Legs: source explicitly says 2200 credits /15 gold; do not derive a conversion.',
                     'Town restrictions and original restock schedules are outside price recovery.'],
            'items':provenance}
    (ROOT/'config/original_shop_prices.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'{len(rows)} items resolved; {len(credits)} credit offers; {len(gold)} gold offers; 1 not sold')

if __name__=='__main__': main()
