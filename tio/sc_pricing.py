"""Ready SC equipment costs more than its expected self-upgrade cost.

Prices use exact arithmetic and the authoritative enhancement probabilities.
Ordinary failures destroy the item, so the model includes starting over and
buying another base item. SE failures lose one level. Successful enhancement
restores full theoretical durability; no extra repair charge is assumed.
"""
from fractions import Fraction
import json


def expected_self_upgrade_cost(base, kit, level, rules, *, kind, special):
    for name, value in (('base', base), ('kit', kit), ('level', level)):
        if type(value) is not int or value < (0 if name == 'level' else 1):
            raise ValueError('Invalid self-upgrade '+name)
    if kind not in ('armor', 'weapon') or type(special) is not bool:
        raise ValueError('Invalid enhancement item kind')
    if not 0 <= rules['safe_levels'] <= rules['max_level'] or level > rules['max_level']:
        raise ValueError('Invalid enhancement level')
    chance = rules[kind+'_success_percent']
    if type(chance) is not int or not 0 <= chance <= 100:
        raise ValueError('Invalid enhancement success probability')
    if special and rules['se_failure_level_loss'] != 1:
        raise ValueError('SC cost model requires one-level SE failure')
    p = Fraction(chance, 100)
    cost, increment = Fraction(base), Fraction(kit)
    for target in range(1, level+1):
        if target <= rules['safe_levels']:
            cost += kit
        elif not p:
            raise ValueError('Cannot price an unreachable enhancement')
        elif special:
            # Additional cost to reach n from n-1; failure falls back to n-2.
            increment = kit/p if target == 1 else (kit + (1-p)*increment) / p
            cost += increment
        else:
            # Every failed attempt requires a replacement and returning to n-1.
            cost = (cost + kit) / p
    return cost


class ReadySCPrices:
    def __init__(self, policy, rules, levels):
        self.policy, self.rules = policy, rules
        self.quantum = policy['round_up_credits']
        self.native_max = policy['native_max_credits']
        self.revision = policy['revision']
        self.percent = {int(k): v for k, v in policy['total_percent_by_level'].items()}
        if (policy['model'] != 'expected_self_upgrade_v1'
                or type(self.quantum) is not int or self.quantum < 1
                or type(self.native_max) is not int or not 1 <= self.native_max <= 0x7fffffff
                or type(self.revision) is not int or not 1 <= self.revision <= 127
                or set(self.percent) != set(levels)-{0}
                or any(type(v) is not int or not 100 < v <= 1000 for v in self.percent.values())):
            raise ValueError('Invalid ready SC price policy')
        ordered = [self.percent[n] for n in sorted(self.percent)]
        if ordered != sorted(ordered):
            raise ValueError('SC convenience premium must not decrease with level')

    def quote(self, base, kit, level, *, kind, special):
        expected = expected_self_upgrade_cost(base, kit, level, self.rules, kind=kind, special=special)
        if level == 0:
            price = base
        else:
            units = expected * self.percent[level] / (100*self.quantum)
            price = ((units.numerator + units.denominator-1)//units.denominator)*self.quantum
        if not 1 <= price <= self.native_max:
            raise ValueError('SC price exceeds the native client credit limit')
        return price


def migrate_carts(db):
    """Invalidate old unpurchased quotes once, without changing any wallet/item."""
    if not db.in_transaction:
        raise ValueError('SC price migration requires a transaction')
    db.execute('CREATE TABLE IF NOT EXISTS sc_price_migrations(id TEXT PRIMARY KEY,receipt TEXT NOT NULL)')
    key='20261014-ready-sc-v1'
    previous=db.execute('SELECT receipt FROM sc_price_migrations WHERE id=?',(key,)).fetchone()
    if previous:
        return json.loads(previous[0])
    tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    receipt={'policy':'expected_self_upgrade_with_ready_premium','cancelled_quotes':{},'wallets_items_changed':False}
    for table in ('sc_cart','sc_cart_terms'):
        if table in tables:
            receipt['cancelled_quotes'][table]=[list(r) for r in db.execute('SELECT * FROM '+table+' ORDER BY account,lot_id')]
            db.execute('DELETE FROM '+table)
    db.execute('INSERT INTO sc_price_migrations VALUES (?,?)',(key,json.dumps(receipt,sort_keys=True)))
    return receipt
