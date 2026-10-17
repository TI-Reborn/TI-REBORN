"""Explicitly funded, pre-existing wallets for tests of paid gameplay features."""
from contextlib import closing
import sqlite3

from tio.wallets import WalletStore


def fund_wallet(path, account, *, credits, gold):
    """Create a test fixture without changing defaults or resetting an existing row."""
    store = WalletStore(path)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('INSERT OR IGNORE INTO wallets(account,credits,gold) VALUES (?,?,?)',
                   (account, credits, gold))
    return store.ensure(account)
