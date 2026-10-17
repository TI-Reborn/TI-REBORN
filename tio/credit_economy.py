"""Single spendable currency; binary Gold slots remain zero for native ABI."""
import json
from functools import lru_cache
from pathlib import Path

@lru_cache(maxsize=1)
def policy():
    p=json.loads((Path(__file__).resolve().parents[1]/'config/credit_economy.json').read_text())
    if p['version']!=1 or p['currency']!='credits':raise ValueError('Invalid credit economy')
    return p

def item_prices():
    return {r['item_id']:r for r in policy()['items']}

def migrate(db):
    """Caller owns the write transaction. Preserve credits/items; retire Gold once."""
    if not db.in_transaction:raise ValueError('Currency migration requires a transaction')
    db.execute('CREATE TABLE IF NOT EXISTS economy_currency_migrations(id TEXT PRIMARY KEY,receipt TEXT NOT NULL)')
    key='credits-only-20261014'
    prior=db.execute('SELECT receipt FROM economy_currency_migrations WHERE id=?',(key,)).fetchone()
    if prior:return json.loads(prior[0])
    tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    audit={'version':1,'policy':'discard_gold_without_conversion','wallets':[],'clans':[],'payables':{},'cancelled_carts':0}
    for table,identifier in (('wallets','account'),('clans','id')):
        if table not in tables:continue
        audit[table]=[list(r) for r in db.execute(f'SELECT {identifier},credits,gold FROM {table} WHERE gold!=0')]
        db.execute(f'UPDATE {table} SET gold=0 WHERE gold!=0')
        for operation in ('INSERT','UPDATE'):
            db.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_retired_gold_{operation.lower()} BEFORE {operation} ON {table} WHEN NEW.gold!=0 BEGIN SELECT RAISE(ABORT,'Gold is retired'); END")
    if 'market_payables' in tables:
        audit['payables']['market']=[list(r) for r in db.execute("SELECT account,amount FROM market_payables WHERE currency='gold'")]
        db.execute("DELETE FROM market_payables WHERE currency='gold'")
        for operation in ('INSERT','UPDATE'):
            db.execute(f"CREATE TRIGGER IF NOT EXISTS market_retired_gold_{operation.lower()} BEFORE {operation} ON market_payables WHEN NEW.currency!='credits' BEGIN SELECT RAISE(ABORT,'Gold is retired'); END")
    if 'bank_gold_payables' in tables:
        audit['payables']['bank']=[list(r) for r in db.execute('SELECT account,gold FROM bank_gold_payables WHERE gold!=0')]
        db.execute('UPDATE bank_gold_payables SET gold=0')
        for operation in ('INSERT','UPDATE'):
            db.execute(f"CREATE TRIGGER IF NOT EXISTS bank_retired_gold_{operation.lower()} BEFORE {operation} ON bank_gold_payables WHEN NEW.gold!=0 BEGIN SELECT RAISE(ABORT,'Gold is retired'); END")
    if 'sc_cart' in tables:
        audit['cancelled_carts']=db.execute('SELECT COUNT(*) FROM sc_cart').fetchone()[0]
        db.execute('DELETE FROM sc_cart')
    if 'sc_cart_terms' in tables:db.execute('DELETE FROM sc_cart_terms')
    if 'sc_auction_lots' in tables:
        audit['retired_auction_lots']=[r[0] for r in db.execute("SELECT id FROM sc_auction_lots WHERE currency='gold'")]
        if 'sc_auction_bots' in tables:
            db.execute("UPDATE sc_auction_bots SET held=0 WHERE lot IN (SELECT id FROM sc_auction_lots WHERE currency='gold')")
        db.execute("UPDATE sc_auction_lots SET state='expired' WHERE currency='gold'")
    audit['credits_changed']=False
    db.execute('INSERT INTO economy_currency_migrations VALUES (?,?)',(key,json.dumps(audit,sort_keys=True)))
    return audit
