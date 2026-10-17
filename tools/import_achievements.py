"""Import the original localization; only verified manual prizes are mapped."""
from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[1]


def main():
    text = Path('C:/Program Files (x86)/TIOnline/base/russian.lng').read_text(encoding='cp1251')
    strings = dict(re.findall(r'^(a[nd]\d\d)\s*=\s*(.*)$', text, re.M))
    metrics = {
        1: ('clan_capture',1), 2: ('clan_defense',1), 3: ('assault_top20',1),
        4: ('kills',10), 5: ('survival_wins',30), 6: ('team_wins',30), 7: ('wall_wins',30),
        8: ('credits_peak',1000000), 9: ('wins',300), 10: ('battles',1000), 11: ('match_kills',6),
        12: ('clan_influence',7500), 13: ('dog_level',5), 14: ('miner_level',6),
        15: ('merc_level',5), 16: ('merc_level',10), 17: ('merc_level',15), 18: ('merc_level',20),
        19: ('attack_kills',2), 20: ('attack_kills',3), 21: ('unseen_kills',1),
        22: ('melee_kills',10), 23: ('light_kills',10), 24: ('automatic_kills',10),
        25: ('distance_kills',10), 26: ('heavy_kills',10), 27: ('throwing_kills',10),
        28: ('miss_streak',3), 29: ('critical_streak',3), 30: ('wall_clean',1), 31: ('team_clean',1),
        32: ('turn_kills',3), 33: ('turn_kills',4), 34: ('crates',500), 35: ('crates',1000),
        36: ('sc_purchase',1), 37: ('premium_purchase',1), 38: ('shop_purchase',1),
        39: ('upgraded_items',1), 40: ('dodge_streak',3), 41: ('upgraded_items',30),
        42: ('upgraded_items',100), 43: ('upgraded_items',500), 44: ('upgraded_items',1000),
        45: ('repairs',1), 46: ('repairs',30), 47: ('repairs',100), 48: ('repairs',500),
        49: ('destroyed_above15',1), 50: ('fist_kills',10),
        60: ('bronze_win',1), 61: ('silver_league',1), 62: ('gold_league',1), 63: ('platinum_league',1),
        64: ('league_streak',3), 65: ('league_streak',10), 66: ('league_streak',25), 67: ('league_streak',50),
    }
    def item(i, count=1, enhancement=0):
        return dict(kind=0,item_id=i,count=count,enhancement=enhancement)
    armor = [item(i, enhancement=1) for i in (239,240,241)]
    prizes = {
        1:[dict(kind=3,value=75)], 2:[dict(kind=3,value=50)], 3:[dict(kind=1,value=1.1)],
        4:[item(317,3),item(10,2)], 5:[*armor,item(306,enhancement=1),item(17,4)],
        6:[*armor,item(302,enhancement=1),item(17,2),item(30)],
        7:[*armor,item(312,enhancement=1),item(17,4)], 9:[item(334,enhancement=20)],
        10:[dict(kind=3,value=75)], 11:[item(33,5)], 12:[dict(kind=1,value=1.05)],
        19:[item(317,enhancement=3)], 20:[item(334,enhancement=3)], 21:[item(33)],
        24:[item(304,enhancement=1)], 25:[item(310,enhancement=1)], 26:[item(307,enhancement=1)],
        27:[item(320,3),item(317,enhancement=1)], 28:[item(17)],
        34:[item(329,enhancement=1)], 50:[item(334,enhancement=1)],
    }
    records=[]
    for i,(metric,goal) in metrics.items():
        records.append(dict(id=i,name=strings[f'an{i:02}'].strip(),description=strings[f'ad{i:02}'].strip(),
                            metric=metric,goal=goal,level=0,prizes=prizes.get(i,[]),
                            reward_source='manual pp25-26' if i in prizes else 'temporary credits',
                            temporary_credits=0 if i in prizes else (100 if i in (36,37,38,39,45) else
                                250 if i in (13,14,15,29,30,31,32,40,60) else
                                500 if i in (16,22,23,33,41,46,61,64) else
                                1000 if i in (17,42,47,62,65) else
                                2500 if i in (18,43,48,49,63,66) else 5000)))
    for r in records:
        if r['id'] in (27,35):r['unmapped_prize']='SubGrenade +1' if r['id']==27 else 'LightTrainer'
    data=dict(source='base/russian.lng an/ad; silver.dll 9637BC/963AC8; https://ti.ggeek.ru/files/TIO_manual.pdf pp25-26',
              policy='One award per account/achievement; user-approved temporary credits where prizes are unrecovered. Unique upgraded item IDs. Battle counters settle on result/escape. Local bots count. Level byte 0 (no additional server tier).',records=records)
    (ROOT/'config/achievements.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main()
