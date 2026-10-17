"""Check the hosted QA cleanup against disposable local SQLite fixtures."""
import ast
from contextlib import closing,redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sqlite3,sys,tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
NAMES=['qm01234567'+s for s in 'abc']


def state(path):
    with closing(sqlite3.connect(path)) as db:
        return {t:db.execute('SELECT * FROM '+t).fetchall() for t, in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def fixture(path,*,foreign_bidder=False):
    with closing(sqlite3.connect(path)) as db,db:
        db.executescript('''
        CREATE TABLE accounts(login TEXT PRIMARY KEY);
        CREATE TABLE wallets(account TEXT PRIMARY KEY,credits INTEGER,gold INTEGER);
        CREATE TABLE clans(id INTEGER PRIMARY KEY,name TEXT,owner TEXT);
        CREATE TABLE private_shops(id INTEGER PRIMARY KEY,account TEXT);
        CREATE TABLE private_shop_sales(shop INTEGER,payload TEXT);
        CREATE TABLE private_shop_orders(shop INTEGER,payload TEXT);
        CREATE TABLE player_auction_lots(id INTEGER PRIMARY KEY,seller TEXT,bidder TEXT);
        CREATE TABLE player_auction_items(lot INTEGER,payload TEXT);
        CREATE TABLE player_auction_history(lot INTEGER,account TEXT);
        CREATE TABLE player_trade_receipts(id TEXT PRIMARY KEY,parties TEXT);
        CREATE TRIGGER player_trade_receipts_no_delete BEFORE DELETE ON player_trade_receipts
          BEGIN SELECT RAISE(ABORT,'immutable'); END;
        ''')
        for name in NAMES+['regular','regular2']:
            db.execute('INSERT INTO accounts VALUES (?)',(name,));db.execute('INSERT INTO wallets VALUES (?,3000,0)',(name,))
        db.execute("INSERT INTO clans VALUES (1,'TestClan','regular')")
        db.executemany('INSERT INTO private_shops VALUES (?,?)',[(1,NAMES[0]),(2,'regular')])
        for table in ('private_shop_sales','private_shop_orders'):
            db.executemany('INSERT INTO '+table+' VALUES (?,?)',[(1,'qa'),(2,'ordinary')])
        db.executemany('INSERT INTO player_auction_lots VALUES (?,?,?)',[(1,NAMES[0],'regular' if foreign_bidder else NAMES[1]),(2,'regular',None)])
        db.executemany('INSERT INTO player_auction_items VALUES (?,?)',[(1,'qa'),(2,'ordinary')])
        db.executemany('INSERT INTO player_auction_history VALUES (?,?)',[(1,NAMES[0]),(1,NAMES[1]),(2,'regular')])
        db.executemany('INSERT INTO player_trade_receipts VALUES (?,?)',[
            ('qa',json.dumps([[NAMES[0],1],[NAMES[1],1]])),('ordinary',json.dumps([['regular',1],['regular2',1]]))])


def main():
    tree=ast.parse((ROOT/'tools/verify_trade_operations_hosted.py').read_text())
    code=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='CLEANUP' for t in n.targets))
    with tempfile.TemporaryDirectory() as folder:
        path=Path(folder)/'fixture.sqlite3';fixture(path);before=state(path)
        with redirect_stdout(StringIO()):
            exec(code.replace('/var/lib/tio-server/reservation.sqlite3',path.as_posix()),{'request':NAMES})
        after=state(path)
        assert after['accounts']==[('regular',),('regular2',)]
        assert after['clans']==before['clans']
        assert after['private_shop_sales']==[(2,'ordinary')]
        assert after['player_auction_items']==[(2,'ordinary')]
        assert after['player_trade_receipts']==[before['player_trade_receipts'][1]]
        path2=Path(folder)/'interference.sqlite3';fixture(path2,foreign_bidder=True);before=state(path2)
        try:
            with redirect_stdout(StringIO()):
                exec(code.replace('/var/lib/tio-server/reservation.sqlite3',path2.as_posix()),{'request':NAMES})
        except AssertionError:pass
        else:raise AssertionError('Cleanup must preserve a real participant transaction')
        assert state(path2)==before
    report=dict(passed=True,checks=2,owned_relations_removed=True,ordinary_accounts_and_TestClan_preserved=True,
                foreign_participant_blocks_deletion=True)
    (ROOT/'reports/trade-operations-20261015/cleanup-checks.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))


if __name__=='__main__':main()
