"""Read-only manual catalog/limits comparison against the captured hosted code."""
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
SNAPSHOT=ROOT/'work/manual-audit-20261018/hosted'
REPORT=ROOT/'reports/manual-audit-20261018'
sys.path.insert(0,str(SNAPSHOT))


def key(s): return re.sub('[^a-z0-9]','',s.casefold()).replace('granade','grenade')


def main():
    records={int(n.get('id')):dict(name=n.get('name'),**{v.get('key'):v.get('val') for v in n.findall('value')})
             for n in ET.parse(SNAPSHOT/'evidence/items_diagnostic.xml').getroot()}
    for row in json.loads((SNAPSHOT/'config/battle_item_catalog_extension.json').read_text())['items']:
        records[row['id']]={'name':row['name'],**row['fields']}
    expected=[]
    def add(page,names): expected.extend((page,n) for n in names.split('|'))
    add('57-66','AK 47|Colt M4|Val|Groza|Famas|P90|HK MP5|UZI|Steyr Aug|Vintorez|AWP|SVD|HK G3SG/1|SKS Carbine|Shotgun|SPAS|Pancor Jackhammer|TOZ-34|M60|Minigun|USP Match|Beretta|Magnum|Desert Eagle|Frag Grenade|Flash Grenade|Sub Grenade|Flare|RPG|Suicide Jacket|Melee Combat|Dog Claws|Knife|Machete|Wrench|Steel Pipe|Freak Melee|Freak Nailgun|Freak Hammer|Freak Shield')
    for family in ('Military','Combat','Light Battle','Adv Military','Adv Combat','Medium Battle','Heavy Military','Heavy Combat','Heavy Battle'):
        add('67-71','|'.join(family+' '+part for part in ('Helmet','Armor','Longies')))
    for family in ('Heavy Combat','Heavy Battle'):
        add('70-71','|'.join(family+' '+part+' SE' for part in ('Helmet','Armor','Longies')))
    add('72-75','Tank Armor|Tank Armor SE|Female Exo Armor|Female Exo Armor SE|Dog Armor|Dog Solid Armor|Dog Solid Armor SE|Freak Helmet|Freak Medium Armor|Freak Medium Legs|Freak Heavy Armor|Freak Heavy Legs')
    add('75-77','7.62 X 39 mm|7.62 X 51 mm|9 X 39 S|9 mm|5.56 X 45 mm|5.7 X 28 mm|Shells|9 X 19 mm Parabellum|Magnum Rounds|Freak Ammo Nails|Vindicator Ammo|Missile')
    add('77-83','Bandage|Bandages Plus|Small Medkit|Small Medkit Plus|Big Medkit|Big Medkit Plus|Health Injection|Health Injection Plus|Repair Kit|Advanced Repair Kit|Super Repair Kit|Upgrade Kit|Binoculars|Night Vision Goggles|Dog Meat|Champagne|Candies|Santa Hat|Mask Neko|Mask Rabbit|Mask Tiger|Light Trainer|Improved Trainer|Ultra Trainer|Light Tactic Advisor|Improved Tactic Advisor|Ultra Tactic Advisor|Light Blocking Exp|Improved Blocking Exp|Ultra Blocking Exp|Injection HP|Injection Vision')
    aliases={'uspmatch':'USP','bandage':'Bandages','dogclaws':'Dog Fangs','injectionvision':'Vision Injection'}
    index={key(v['name']):(i,v) for i,v in records.items()}
    rows=[]
    for pages,name in expected:
        found=index.get(key(name)) or index.get(key(aliases.get(key(name),'')))
        rows.append(dict(pages=pages,name=name,template=None if found is None else found[0],catalog_name=None if found is None else found[1]['name']))
    from tio.weapon_proficiency import ProficiencyRules
    manual_single=[59,69,78,88,97,106,116,125,134,144,153,163,172,181,191,200,200,200,200,200]
    manual_total=[270,280,290,300,315,330,355,375,400,425,450,470,490,510,530,550,570,590,610,630]
    caps=[dict(level=l,manual_single=manual_single[l-1],manual_total=manual_total[l-1],hosted_single=ProficiencyRules().caps(l,True)[0],hosted_total=ProficiencyRules().caps(l,True)[1]) for l in range(1,21)]
    result=dict(catalog_count=len(records),manual_entries=len(rows),matched=sum(r['template'] is not None for r in rows),items=rows,skill_caps=caps)
    (REPORT/'catalog-comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# Именованные предметы из мануала: проверка наличия в каталоге хостинга','',
           'Сопоставление имён и шаблонов, а не доказательство работоспособности эффектов, доступности в магазине или совпадения каждой характеристики. Страницы печатные. Отсутствие совпадения имени требует проверки псевдонима/ресурса, а не автоматического вывода об отсутствии механики.','',
           '| Страницы | Мануал | Шаблон на хостинге | Имя в каталоге |','|---|---|---|---|']
    lines += [f"| {r['pages']} | {r['name']} | {r['template'] if r['template'] is not None else 'не сопоставлен'} | {r['catalog_name'] or '—'} |" for r in rows]
    (REPORT/'catalog-comparison.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(dict(entries=len(rows),matched=result['matched'],unmatched=[r['name'] for r in rows if r['template'] is None],caps=caps),ensure_ascii=False))


if __name__=='__main__': main()
