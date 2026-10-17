"""Server-only arena inputs and exact, auditable credit calculations."""
from dataclasses import dataclass
from fractions import Fraction
import json
import time


@dataclass(frozen=True)
class RewardContext:
    levels: tuple
    opponents: tuple  # (human account OR integer bot seat, starting soldier levels)
    active: bool
    town_id: int | None = None


def calculate(db, account, match_id, result, context, rank_percent, *, escaped=False, now=None):
    audit = dict(version=2, base=0, outcome=0, strength=0, participation=0,
                 repeat=0, progression_repeat='1', rank_percent=rank_percent, opponents=[])
    if context is None:
        return 0, json.dumps(audit, sort_keys=True)
    levels = context.levels
    opponents = context.opponents
    if not levels or any(type(l) is not int or not 1 <= l <= 20 for l in levels):
        raise ValueError('Invalid reward levels')
    identities = [name for name, _ in opponents]
    if (not identities or any(not ((type(n) is str and n) or
                                   (type(n) is int and 0<n<=0xffffffff)) for n in identities)
            or len(set(identities)) != len(identities) or account in identities):
        raise ValueError('Invalid reward opponents')
    # Bot seats are frozen server owner IDs, never invented accounts or
    # repeat-pair partners. Existing string-only PvP reports remain unchanged.
    names = [name for name in identities if type(name) is str]
    bots = [name for name in identities if type(name) is int]
    enemy_levels = tuple(l for _, squad in opponents for l in squad)
    if any(not squad for _, squad in opponents) or any(type(l) is not int or not 1 <= l <= 20 for l in enemy_levels):
        raise ValueError('Invalid opponent levels')
    db.execute('''CREATE TABLE IF NOT EXISTS reward_pairs (
        match_id TEXT NOT NULL, first_account TEXT NOT NULL, second_account TEXT NOT NULL,
        settled_at REAL NOT NULL, factor_quarters INTEGER NOT NULL,
        PRIMARY KEY(match_id,first_account,second_account))''')
    db.execute('CREATE INDEX IF NOT EXISTS reward_pairs_history ON reward_pairs(first_account,second_account,settled_at)')
    stamp = time.time() if now is None else now
    factors = []
    for opponent in sorted(names):
        first, second = sorted((account, opponent))
        previous = db.execute('SELECT factor_quarters FROM reward_pairs WHERE match_id=? AND first_account=? AND second_account=?',
                              (match_id, first, second)).fetchone()
        if previous is None:
            count = db.execute('SELECT count(*) FROM reward_pairs WHERE first_account=? AND second_account=? AND settled_at>? AND settled_at<=?',
                               (first, second, stamp-21600, stamp)).fetchone()[0]
            factor = 4 if count < 3 else 2 if count < 6 else 1
            db.execute('INSERT INTO reward_pairs VALUES (?,?,?,?,?)', (match_id, first, second, stamp, factor))
        else:
            factor = previous[0]
        factors.append(Fraction(factor, 4))
    level = Fraction(sum(levels), len(levels))
    base = 100 + 3*(level-1)
    strength = min(Fraction(115,100), max(Fraction(1,2), Fraction(sum(enemy_levels),len(enemy_levels))/level))
    outcome = Fraction(0) if escaped else (Fraction(1,4), Fraction(1), Fraction(1,2))[result]
    repeat = sum(factors)/len(factors) if factors else Fraction(1)
    # Damage/kill reports aggregate opponents. Using their average here would
    # let a repeatedly farmed victim regain progression by adding a fresh
    # teammate. Progression therefore uses the most repeated opposing pair.
    progression_repeat = min(factors) if factors else Fraction(1)
    credit_factor = (sum(factors)+Fraction(len(bots),2))/len(identities)
    from .cities import CITIES
    city=CITIES.get(context.town_id)
    profit=city.profit if city else 1
    frozen=None
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='world_city_matches'").fetchone():
        if db.execute('SELECT 1 FROM world_city_matches WHERE match_id=?',(match_id,)).fetchone():
            from .world_completion import frozen_city
            frozen=frozen_city(db,match_id)
            if context.town_id!=frozen['town_id']:raise ValueError('Frozen city differs from reward context')
            profit=Fraction(frozen['profit'])
    gross = int(base * outcome * strength * int(context.active) * credit_factor * Fraction(100+rank_percent,100) * profit)
    audit.update(base=str(base), level=str(level), outcome=str(outcome), strength=str(strength),
                 participation=int(context.active), repeat=str(repeat), opponents=sorted(names),
                 progression_repeat=str(progression_repeat),
                 levels=levels, enemy_levels=enemy_levels,town_id=context.town_id,
                 city_profit=int(profit) if Fraction(profit).denominator==1 else str(profit))
    if frozen is not None:audit['city_coefficients']=frozen
    if bots:
        audit.update(version=3,credit_factor=str(credit_factor),
                     bot_credit_factor=str(Fraction(2*len(names)+len(bots),2*len(identities))),
                     bot_opponents=[dict(owner=n,levels=ls,credit_rate='1/2')
                                    for n,ls in sorted(opponents,key=lambda r:str(r[0])) if type(n) is int])
    return gross, json.dumps(audit, sort_keys=True)
