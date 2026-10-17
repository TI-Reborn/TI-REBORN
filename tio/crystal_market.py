"""Persistent crystals and fixed-point quotes; no floating-point money writes."""

from .db_transaction import connect
from contextlib import closing
from dataclasses import replace
from pathlib import Path
import json
import sqlite3
import time

POLICY=json.loads((Path(__file__).resolve().parents[1]/'config/mining.json').read_text())
SCALE=10_000_000


class CrystalMarket:
    def __init__(self,path,*,clock=time.time):
        self.path=path; self.clock=clock
        with closing(connect(path)) as db,db:
            db.execute('CREATE TABLE IF NOT EXISTS crystal_wallets (account TEXT PRIMARY KEY, amount INTEGER NOT NULL CHECK(amount BETWEEN 0 AND 4294967295))')
            db.execute('CREATE TABLE IF NOT EXISTS crystal_market (id INTEGER PRIMARY KEY CHECK(id=1), rate INTEGER NOT NULL, updated INTEGER NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS crystal_extractions (match_id TEXT, account TEXT, amount INTEGER NOT NULL, PRIMARY KEY(match_id,account))')
            db.execute('CREATE TABLE IF NOT EXISTS crystal_sales (id INTEGER PRIMARY KEY, account TEXT, amount INTEGER, credits INTEGER, rate INTEGER, sold INTEGER)')
            db.execute('''CREATE TABLE IF NOT EXISTS crystal_quote_history (
                id INTEGER PRIMARY KEY,observed INTEGER NOT NULL,rate INTEGER NOT NULL)''')
            from .mine_claims import schema as claim_schema
            claim_schema(db)
            db.execute('''CREATE TABLE IF NOT EXISTS mine_crystal_extractions (
                match_id TEXT NOT NULL,extractor TEXT NOT NULL,location INTEGER NOT NULL,
                gross INTEGER NOT NULL,tax INTEGER NOT NULL,claim_json TEXT NOT NULL,
                request_json TEXT NOT NULL,receipt_json TEXT NOT NULL,
                PRIMARY KEY(match_id,extractor))''')
            db.execute('INSERT OR IGNORE INTO crystal_market VALUES (1,?,?)',(POLICY['market_initial_rate_units'],int(clock())))

    def balance(self,account):
        with closing(connect(self.path)) as db:
            row=db.execute('SELECT amount FROM crystal_wallets WHERE account=?',(account,)).fetchone()
            return row[0] if row else 0

    def project(self,account,assets):
        # Native quotes GUI6ef364 reads character+240: AssetCount field5.
        return replace(assets,spectra_crystals=self.balance(account))

    def _rate(self,db):
        rate,updated=db.execute('SELECT rate,updated FROM crystal_market WHERE id=1').fetchone()
        steps=max(0,(int(self.clock())-updated)//POLICY['market_rise_interval'])
        if steps:
            rate+=steps*POLICY['market_rise_units']
            db.execute('UPDATE crystal_market SET rate=?,updated=? WHERE id=1',(rate,updated+steps*POLICY['market_rise_interval']))
        self._observe(db,rate)
        return rate

    def _observe(self,db,rate):
        # Store actual accepted server quotes, never fabricate missing candles
        # for periods before this feature existed or while the server was idle.
        previous=db.execute('SELECT rate FROM crystal_quote_history ORDER BY id DESC LIMIT 1').fetchone()
        if previous is None or previous[0]!=rate:
            db.execute('INSERT INTO crystal_quote_history(observed,rate) VALUES (?,?)',(int(self.clock()),rate))
            limit=POLICY.get('market_history_points',144)
            db.execute('DELETE FROM crystal_quote_history WHERE id NOT IN (SELECT id FROM crystal_quote_history ORDER BY id DESC LIMIT ?)',(limit,))

    def quote_history(self):
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE');rate=self._rate(db)
            values=db.execute('SELECT rate FROM crystal_quote_history ORDER BY id').fetchall()
            # B01F has four price floats per candle and no timestamps. Each
            # recorded quote is a point candle: every bound equals its price.
            return rate/SCALE,tuple((n/SCALE,)*4 for (n,) in values)

    def rate(self):
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE')
            return self._rate(db)/SCALE

    @staticmethod
    def extract(db,account,match_id,amount):
        """Call inside the same transaction as battle wounds/settlement."""
        if type(amount) is not int or not 0<=amount<=0xffffffff:raise ValueError('Invalid extraction')
        previous=db.execute('SELECT amount FROM crystal_extractions WHERE match_id=? AND account=?',(match_id,account)).fetchone()
        if previous:
            if previous[0]!=amount:raise ValueError('Conflicting extraction receipt')
            return
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='mine_crystal_extractions'").fetchone() and db.execute('SELECT 1 FROM mine_crystal_extractions WHERE match_id=?',(match_id,)).fetchone():
            raise ValueError('Shared mine extraction requires the frozen shared receipt')
        db.execute('INSERT OR IGNORE INTO crystal_wallets VALUES (?,0)',(account,))
        db.execute('UPDATE crystal_wallets SET amount=amount+? WHERE account=?',(amount,account))
        db.execute('INSERT INTO crystal_extractions VALUES (?,?,?)',(match_id,account,amount))

    @staticmethod
    def settle_mine(db,match_id,*,gross,role,extractor,claim,miner=None,defender=None,raiders=None):
        """Settle one authoritative squad exit inside its battle transaction.

        The server freezes the miner/defender pair and claim in its durable
        outbox. Admission checked real owner-clan membership; leaving the clan
        later does not change the earned escort share. Raider extraction is
        untaxed. Integer remainder goes to the defender (or solo extractor),
        preserving every extracted crystal. No UI-supplied amount reaches here.
        """
        if not db.in_transaction:raise ValueError('Mine extraction requires a transaction')
        from .mine_claims import validate_claim,validate_frozen,LOCATIONS
        claim=validate_claim(claim)
        if not isinstance(match_id,str) or not match_id:raise ValueError('Invalid extraction match')
        if type(gross) is not int or not 0<=gross<=0xffffffff:raise ValueError('Invalid extraction')
        if type(role) is not int or role not in (1,2,3):raise ValueError('Invalid extraction role')
        if not isinstance(extractor,str) or not extractor:raise ValueError('Invalid extractor account')
        if any(a is not None and (not isinstance(a,str) or not a) for a in (miner,defender)):
            raise ValueError('Invalid extraction participant')
        if miner is not None and miner==defender:raise ValueError('Invalid mining escort pair')
        if role==1 and miner!=extractor or role==3 and (defender!=extractor or miner is None):
            raise ValueError('Extractor does not match the frozen mining role')
        if role==2 and extractor in (miner,defender):raise ValueError('Raider cannot be the mining escort')
        if raiders is not None:
            if role!=2 or not isinstance(raiders,(list,tuple)) or not 1<=len(raiders)<=2 or len(set(raiders))!=len(raiders):
                raise ValueError('Invalid frozen raider pair')
            if extractor not in raiders or any(not isinstance(a,str) or not a for a in raiders):raise ValueError('Invalid raider recipient')
        if role in (1,3) and defender is not None and claim['owner_clan'] is None:
            raise ValueError('An unowned checkpoint cannot have a defender')
        request=dict(gross=gross,role=role,extractor=extractor,claim=claim,miner=miner,defender=defender)
        if raiders is not None:request['raiders']=list(raiders)
        canonical=lambda value:json.dumps(value,sort_keys=True,separators=(',',':'))
        request_json=canonical(request)
        prior=db.execute('SELECT request_json,receipt_json FROM mine_crystal_extractions WHERE match_id=? AND extractor=?',
                         (match_id,extractor)).fetchone()
        if prior:
            if prior[0]!=request_json:raise ValueError('Conflicting mine extraction receipt')
            return json.loads(prior[1])
        validate_frozen(db,claim)
        if db.execute('SELECT 1 FROM crystal_extractions WHERE match_id=? AND account=?',(match_id,extractor)).fetchone():
            raise ValueError('Extraction already settled by the legacy mining path')
        claim_json=canonical(claim)
        earlier=db.execute('SELECT location,claim_json,gross FROM mine_crystal_extractions WHERE match_id=?',(match_id,)).fetchall()
        if gross and any(n>0 for _,_,n in earlier):raise ValueError('Mining mission already ended with an extraction')
        if any(location!=claim['location'] or frozen!=claim_json for location,frozen,_ in earlier):
            raise ValueError('Mine extraction checkpoint changed within a battle')
        total=POLICY['bands'][LOCATIONS[claim['location']]['band']][2]
        if gross+sum(n for _,_,n in earlier)>total:
            raise ValueError('Extraction exceeds the entire mine deposit capacity')
        tax=0 if role==2 else gross*claim['tax_percent']//100
        if role==2 and raiders is not None:
            payouts={account:gross//len(raiders) for account in raiders}
            payouts[raiders[-1]]+=gross-sum(payouts.values())
        elif role in (1,3) and defender is not None:
            payouts={miner:gross//2,defender:gross-tax-gross//2}
        else:payouts={extractor:gross-tax}
        if tax+sum(payouts.values())!=gross:raise ValueError('Crystal extraction conservation failed')
        balances={}
        for account,amount in payouts.items():
            if not db.execute('SELECT 1 FROM wallets WHERE account=?',(account,)).fetchone():
                raise ValueError('Extraction recipient wallet missing')
            row=db.execute('SELECT amount FROM crystal_wallets WHERE account=?',(account,)).fetchone()
            balance=row[0] if row else 0
            if balance+amount>0xffffffff:raise ValueError('Crystal balance overflow')
            balances[account]=balance+amount
        owner=claim['owner_clan']
        treasury=0
        if tax:
            row=db.execute('SELECT amount FROM clan_crystals WHERE clan_id=?',(owner,)).fetchone()
            treasury=row[0] if row else 0
            if treasury+tax>0xffffffff:raise ValueError('Clan crystal balance overflow')
        receipt=dict(match_id=match_id,extractor=extractor,location=claim['location'],gross=gross,
                     tax=tax,owner_clan=owner,payouts=payouts)
        for account,balance in balances.items():
            db.execute('''INSERT INTO crystal_wallets VALUES (?,?) ON CONFLICT(account)
                DO UPDATE SET amount=excluded.amount''',(account,balance))
        if tax:
            db.execute('''INSERT INTO clan_crystals VALUES (?,?) ON CONFLICT(clan_id)
                DO UPDATE SET amount=excluded.amount''',(owner,treasury+tax))
            from .clans import record
            record(db,owner,extractor,'mine_tax',canonical(receipt))
        db.execute('INSERT INTO crystal_extractions VALUES (?,?,?)',(match_id,extractor,gross))
        db.execute('INSERT INTO mine_crystal_extractions VALUES (?,?,?,?,?,?,?,?)',
                   (match_id,extractor,claim['location'],gross,tax,claim_json,request_json,canonical(receipt)))
        if gross:
            from .mine_rounds import record_mission
            import time
            record_mission(db,match_id,1 if role==2 else 0,gross,now=time.time())
        return receipt

    def sell(self,account,amount):
        if type(amount) is not int or not POLICY['market_sale_min']<=amount<=POLICY['market_sale_max']:
            raise ValueError('Sell between 1000 and 50000 crystals')
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE')
            balance=db.execute('SELECT amount FROM crystal_wallets WHERE account=?',(account,)).fetchone()
            wallet=db.execute('SELECT credits,gold FROM wallets WHERE account=?',(account,)).fetchone()
            if balance is None or balance[0]<amount or wallet is None:raise ValueError('Insufficient crystals')
            rate=self._rate(db); credits=amount*rate//SCALE
            if wallet[0]+credits>0xffffffff:raise ValueError('Credit balance overflow')
            db.execute('UPDATE crystal_wallets SET amount=amount-? WHERE account=?',(amount,account))
            db.execute('UPDATE wallets SET credits=credits+? WHERE account=?',(credits,account))
            db.execute('UPDATE crystal_market SET rate=? WHERE id=1',(max(POLICY['market_min_rate_units'],rate-amount),))
            self._observe(db,max(POLICY['market_min_rate_units'],rate-amount))
            db.execute('INSERT INTO crystal_sales(account,amount,credits,rate,sold) VALUES (?,?,?,?,?)',(account,amount,credits,rate,int(self.clock())))
            from .achievements import update
            update(db,account,maximum={'credits_peak':wallet[0]+credits})
        return credits
