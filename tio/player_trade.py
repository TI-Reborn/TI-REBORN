"""Atomic direct barter between selected soldiers of two different accounts.

Drafts never debit funds or remove goods. A durable immutable receipt and both
inventories/wallets commit together. Restart therefore cancels every inert draft.
"""
from dataclasses import replace
import hashlib,json
from .db_transaction import transaction
from .protocol.item_list import encode_item_list,decode_item_list
from .protocol.player_trade import CURRENCIES
from . import market_inventory as inv
from .item_stacking import merge_stacks,stack_key
from .inventory_capacity import validate_capacity

def tradable(item):
    # The native barter record lacks 6A's special-enhancement field. Do not
    # present such an item without its complete terms.
    return inv.tradable(item) and not item.unknown_bytes_03[2]

class TradeStore:
    def __init__(self,path):
        self.path=path
        from .warehouse import WarehouseStore
        from .wallets import WalletStore
        WarehouseStore(path);WalletStore(path)
        with transaction(path) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS player_trade_receipts (
                id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, parties TEXT NOT NULL,
                result TEXT NOT NULL, occurred INTEGER NOT NULL)''')
            for op in ('UPDATE','DELETE'):
                db.execute(f"CREATE TRIGGER IF NOT EXISTS player_trade_receipts_no_{op.lower()} BEFORE {op} ON player_trade_receipts BEGIN SELECT RAISE(ABORT,'Trade receipts are immutable'); END")

    @staticmethod
    def selected(db,account,pet):
        inv.owner(db,account);inv.unsigned(pet,positive=True)
        owned=inv.owned(db,account)
        row=db.execute('SELECT inventory_packet FROM owned_pets WHERE account=? AND pet_id=?',(account,pet)).fetchone()
        if row is None:raise ValueError('Выбранный боец не принадлежит аккаунту')
        _,items,flag=decode_item_list(row[0])
        return items,flag,owned

    def available(self,account,pet):
        with transaction(self.path) as db:
            items,_,_=self.selected(db,account,pet)
            wallet=db.execute('SELECT credits,gold FROM wallets WHERE account=?',(account,)).fetchone()
            # Signed native quantities: expose a bounded spendable part.
            return tuple(i for i in items if i.instance_id<0xffff0000 and tradable(i)),tuple(min(v,0x7fffffff) for v in wallet)

    def commit(self,identity,parties,offers,expected,now):
        if len(parties)!=2 or len({a for a,p in parties})!=2:raise ValueError('Два разных владельца обязательны')
        payload=json.dumps([parties,offers,expected],sort_keys=True,separators=(',',':'))
        fingerprint=hashlib.sha256(payload.encode()).hexdigest()
        with transaction(self.path) as db:
            prior=db.execute('SELECT fingerprint,result FROM player_trade_receipts WHERE id=?',(identity,)).fetchone()
            if prior:
                if prior[0]!=fingerprint:raise ValueError('Trade receipt conflict')
                return json.loads(prior[1])
            snapshots={};remaining={};incoming={a:[] for a,p in parties};balances={};flags={}
            for account,pet in parties:
                items,flag,owned=self.selected(db,account,pet)
                snapshots[account]=items;remaining[account]={i.instance_id:i for i in items};flags[account]=flag
                balances[account]=list(db.execute('SELECT credits,gold FROM wallets WHERE account=?',(account,)).fetchone())
                for key,count in offers[account].items():
                    key=int(key);inv.unsigned(count,0x7fffffff,positive=True)
                    if key in CURRENCIES:
                        index=0 if CURRENCIES[key]=='credits' else 1
                        if count>balances[account][index]:raise ValueError('Недостаточно средств для обмена')
                    else:
                        item=remaining[account].get(key)
                        if item is None or not tradable(item) or count>item.count:
                            raise ValueError('Предмет недоступен для обмена')
                        if encode_item_list(pet,(item,)).hex()!=expected[account].get(str(key)):
                            raise ValueError('Предмет изменился во время обмена')
                        if stack_key(item) is None and (count!=1 or item.count!=1):
                            raise ValueError('Это не стопка предметов')
            # Remove every outgoing item before allocating destination IDs.
            for index,(account,pet) in enumerate(parties):
                other=parties[1-index][0]
                for key,count in offers[account].items():
                    key=int(key)
                    if key in CURRENCIES:
                        currency=0 if CURRENCIES[key]=='credits' else 1
                        balances[account][currency]-=count;balances[other][currency]+=count
                    else:
                        item=remaining[account][key];incoming[other].append(replace(item,unknown_u32_01=count))
                        if count==item.count:del remaining[account][key]
                        else:remaining[account][key]=replace(item,unknown_u32_01=item.count-count)
            result={}
            for account,pet in parties:
                if any(v>inv.MAX for v in balances[account]):raise ValueError('Кошелёк получателя переполнен')
                owned=inv.owned(db,account)
                sequence=db.execute('SELECT next_id FROM item_sequences WHERE account=?',(account,)).fetchone()
                next_id=max(max(owned,default=0)+1,sequence[0] if sequence else 1)
                added=[]
                for item in incoming[account]:
                    if next_id>=0xffff0000:raise ValueError('Исчерпаны ID предметов')
                    added.append(replace(item,instance_id=next_id,unknown_u8_01=0,location_raw=0));next_id+=1
                merged=merge_stacks((*remaining[account].values(),*added))
                validate_capacity(snapshots[account],merged)
                packet=encode_item_list(pet,merged,flags[account])
                db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=?',(packet,account,pet))
                db.execute('UPDATE wallets SET credits=?,gold=? WHERE account=?',(*balances[account],account))
                db.execute('INSERT INTO item_sequences VALUES (?,?) ON CONFLICT(account) DO UPDATE SET next_id=MAX(next_id,excluded.next_id)',(account,next_id))
                result[account]=dict(pet=pet,inventory=packet.hex(),credits=balances[account][0],gold=balances[account][1])
            db.execute('INSERT INTO player_trade_receipts VALUES (?,?,?,?,?)',(identity,fingerprint,json.dumps(parties),json.dumps(result),now))
            return result
