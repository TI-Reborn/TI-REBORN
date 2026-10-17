"""Read-only bonuses from earned immutable achievement reward snapshots.

Prize delivery and notification flags do not control eligibility. Rating
rewards add once per earned achievement; influence uses the highest coefficient
and excludes premium, medals and clan policy, which callers apply separately.
"""
from fractions import Fraction
import json
import math

MAX=0xffffffff


def bonus_value(prize):
    """Validate relevant original B5 reward kinds; other kinds have no bonus."""
    kind=prize.get('kind')
    if type(kind) is not int:return None
    value=prize.get('value')
    if kind==3:
        if type(value) is not int or not 0<=value<=MAX:raise ValueError('Invalid earned achievement rating bonus')
        return value
    if kind==1:
        if type(value) not in (int,float) or not math.isfinite(value):raise ValueError('Invalid earned achievement influence bonus')
        factor=Fraction(str(value))
        if not 1<=factor<=MAX:raise ValueError('Invalid earned achievement influence coefficient')
        return factor
    return None


def earned_prizes(db,account):
    """Read existing awards without creating tables or consulting the catalog."""
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='achievement_awards'").fetchone():return ()
    result=[];seen={}
    for identity,body in db.execute('SELECT id,body FROM achievement_awards WHERE account=? ORDER BY id',(account,)):
        if type(identity) is not int or not 1<=identity<=MAX:raise ValueError('Invalid earned achievement identity')
        if identity in seen:
            if seen[identity]!=body:raise ValueError('Conflicting duplicate earned achievement')
            continue
        seen[identity]=body
        try:row=json.loads(body)
        except (TypeError,ValueError) as error:raise ValueError('Invalid earned achievement snapshot') from error
        if not isinstance(row,dict) or not isinstance(row.get('prizes'),list) or len(row['prizes'])>255 or any(not isinstance(p,dict) for p in row['prizes']):raise ValueError('Invalid earned achievement prizes')
        result.extend(row['prizes'])
    return tuple(result)


def rating_bonus(db,account):
    return min(MAX,sum(bonus_value(p) for p in earned_prizes(db,account) if type(p.get('kind')) is int and p['kind']==3))


def influence_multiplier(db,account):
    return max((bonus_value(p) for p in earned_prizes(db,account) if type(p.get('kind')) is int and p['kind']==1),default=Fraction(1))


def total_rating(db,account,base):
    """Retain legacy negative PvP rating; saturate to the existing native field."""
    if type(base) is not int:raise ValueError('Invalid base player rating')
    return min(0x7fffffff,max(-(1<<31),base+rating_bonus(db,account)))
