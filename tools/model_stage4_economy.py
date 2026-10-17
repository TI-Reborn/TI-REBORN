"""Source-backed local economy scenarios, never a hosted/graphical QA claim."""
from fractions import Fraction
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tio.city_catalogs import CityCatalogs
from tio.level_progression import FLOORS, level_for_xp
from tio.wallets import STARTING_CREDITS, STARTING_GOLD


def model():
    catalogs = CityCatalogs(ROOT/'config/city_catalogs.json')
    offers = {o.item_id: o for values in catalogs.items.values() for o in values}
    achievements = json.loads((ROOT/'config/achievements.json').read_text(encoding='utf-8'))['records']
    first_shop = next(r['temporary_credits'] for r in achievements if r['metric']=='shop_purchase' and r['goal']==1)
    recovery = json.loads((ROOT/'config/recovery.json').read_text(encoding='utf-8'))
    ammo, gun, kit = offers[3], offers[301], offers[17]
    start = STARTING_CREDITS
    purchase_cash = start-ammo.unknown_u32_03+first_shop
    example = dict(start_wallet=[start,STARTING_GOLD],free_starter_gun=301,
        ammo_pack=dict(rounds=ammo.unknown_u32_02,price=ammo.unknown_u32_03),
        first_shop_achievement=first_shop,cash_after_first_purchase=purchase_cash,
        assumptions='equal active level1 Reservation PvP; own100HP; no premium/rental/rank credit bonus; one ordinary damage budget; selected shot counts are illustrative, not observed',
        winner=dict(damage_dealt=100,damage_received=60,credit_reward=100,paid_treatment=120,
                    cash_after_treatment=purchase_cash+100-120,accepted_shots=10,rounds_left=40,weapon_durability=270,xp_before_strength_repeat=520),
        loser=dict(damage_dealt=60,damage_received=100,credit_reward=25,paid_treatment=200,
                   cash_after_treatment=purchase_cash+25-200,accepted_shots=6,rounds_left=44,weapon_durability=282,xp_before_strength_repeat=440),
        free_full_recovery_seconds=100*10,
        repair_kit=dict(price=kit.unknown_u32_03,resource=kit.durability,
            first_repair_achievement=next(r['temporary_credits'] for r in achievements if r['metric']=='repairs' and r['goal']==1),
            example_deficit30=dict(restored=29,max_loss=1,resource_left=kit.durability-29)),
        recruit=dict(human_price=next(c.price_credits for c in catalogs.candidates if c.resource_type==1),
                     beretta_price=gun.unknown_u32_03,ammo_pack_price=ammo.unknown_u32_03,armed_total=300,
                     six_armed_recruits_total=1800,cash_after_starter_ammo_and_six_armed_recruits=purchase_cash-1800))
    progression = {}
    for name, repeated in (('fresh_equal_opponents',False),('same_pair_within_six_hours',True)):
        xp, records, thresholds = 0, [], {}
        for battle in range(1,101):
            level = level_for_xp(xp)
            hp = 100+5*(level-1)
            factor = Fraction(1) if not repeated or battle<=3 else Fraction(1,2) if battle<=6 else Fraction(1,4)
            raw_gain = int(Fraction(26,5)*hp)
            gain = int(raw_gain*factor)
            xp += gain
            after = level_for_xp(xp)
            if after>=2 and 2 not in thresholds: thresholds[2]=battle
            if after>=3 and 3 not in thresholds: thresholds[3]=battle
            if after>=4 and 4 not in thresholds: thresholds[4]=battle
            if battle<=12: records.append(dict(battle=battle,starting_level=level,max_hp=hp,
                repeat=str(factor),xp_gain=gain,xp_after=xp,level_after=after))
            if after>=4: break
        progression[name] = dict(estimated_battles_to_level=thresholds,first12=records)
    return dict(kind='local source-backed model; neither observed hosted outcomes nor original server formula',
        first_battle=example,level_floors=list(FLOORS),progression=progression,
        progression_assumptions=['starter baseHP100 preserved from the actual onboarding fixture; levels add5',
            'deal one enemy maxHP and receive60% own maxHP each battle; equal starting levels/ranks/upgrade; floor once before repeat',
            'opponent mirrors level/HP; no additional achievement XP, premium, waiting/cooldown or missed hits',
            'same-pair branch assumes all counted fights inside6hours; real battle duration/cooldown can change factors',
            'actual damage/strength differs; hosted verifier derives each persisted XP from its actual match'])


if __name__=='__main__':
    output=ROOT/'reports/economy/balance-model.json'
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(model(),indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=True,remote_contacted=False,report=str(output))))
