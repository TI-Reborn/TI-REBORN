"""Persistent account starting funds; seeding never resets an existing wallet."""

from .db_transaction import connect
from contextlib import closing
import sqlite3
from pathlib import Path
from .protocol.asset_count import AssetCount

STARTING_CREDITS = 3_000
STARTING_GOLD = 0


class WalletStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(connect(self.path)) as db, db:
            db.execute('''CREATE TABLE IF NOT EXISTS wallets (
                account TEXT PRIMARY KEY NOT NULL,
                credits INTEGER NOT NULL CHECK(credits BETWEEN 0 AND 4294967295),
                gold INTEGER NOT NULL CHECK(gold BETWEEN 0 AND 4294967295))''')

    def ensure(self, account):
        if not isinstance(account, str) or not account:
            raise ValueError('Account required')
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT OR IGNORE INTO wallets VALUES (?, ?, ?)',
                       (account, STARTING_CREDITS, STARTING_GOLD))
            if (db.execute("SELECT 1 FROM sqlite_master WHERE name='bank_gold_payables'").fetchone()
                    and db.execute('SELECT 1 FROM bank_gold_payables WHERE account=? AND gold>0',(account,)).fetchone()):
                from .bank_economy import collect_paid_gold
                collect_paid_gold(db,account)
            credits, gold = db.execute(
                'SELECT credits,gold FROM wallets WHERE account=?', (account,)).fetchone()
            crystals=0
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='crystal_wallets'").fetchone():
                row=db.execute('SELECT amount FROM crystal_wallets WHERE account=?',(account,)).fetchone()
                crystals=row[0] if row else 0
            from .shooting_range import token_assets
            from .premium import project
            from .clans import project_assets
            from .bank_economy import project_assets as project_bank
            return project_bank(db,account,project_assets(db,account,project(db,account,token_assets(db, account, AssetCount(credits, gold,spectra_crystals=crystals)))))
