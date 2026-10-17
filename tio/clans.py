"""Account-bound clans. All decisions and shared-asset writes use SQLite authority.

No player data is seeded. A pending invitation grants no membership and the
inviter's current rights are checked again at acceptance. Membership IDs use a
persistent sequence, independent of each account's local character ID.
"""
from contextlib import closing
from dataclasses import replace
import time
import unicodedata
from .db_transaction import connect
from .owned_pets import OwnedPetStore
from .protocol.pet_info import decode_pet_info
from .protocol.item_list import decode_item_list,encode_item_list,ItemRecord
from .warehouse import WarehouseStore,WarehouseRejected
from .item_stacking import merge_stacks
from .inventory_capacity import validate_capacity

INVITE=2
social_completion_installed=True
VIEW_WAREHOUSE=8
WITHDRAW_WAREHOUSE=16
KICK=128
CREST=256
UPGRADE=1024
ASSAULT=2048
VIEW_SAFE=32768
WITHDRAW_UPGRADES=65536
WITHDRAW_REPAIR=131072
WITHDRAW_CRYSTALS=262144
WITHDRAW_CREDITS=524288
WITHDRAW_GOLD=1048576
KNOWN_RIGHTS=(INVITE|VIEW_WAREHOUSE|WITHDRAW_WAREHOUSE|KICK|CREST|UPGRADE|ASSAULT|
              VIEW_SAFE|WITHDRAW_UPGRADES|WITHDRAW_REPAIR|WITHDRAW_CRYSTALS|WITHDRAW_CREDITS|WITHDRAW_GOLD)
DEFAULT_RIGHTS=VIEW_WAREHOUSE|VIEW_SAFE
CAPACITY=32  # Server storage policy, not an inferred historical clan limit.
MEMBER_LIMITS=(10,16,20)
# Original item51 is Crystals (items_diagnostic.xml); native7d4e58 copies
# personal character+240 into that currency record. IDs here are server-issued
# projections, not persistent inventory objects or recovered original IDs.
CRYSTAL_MONEY_ID=0xffff0033
MONEY_IDS={0xffff0001:('credits',1,WITHDRAW_CREDITS),
           CRYSTAL_MONEY_ID:('crystals',51,WITHDRAW_CRYSTALS)}


class ClanRejected(WarehouseRejected):pass


def schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS clans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,name BLOB NOT NULL,name_key TEXT NOT NULL UNIQUE,
        leader TEXT NOT NULL UNIQUE,level INTEGER NOT NULL DEFAULT 0 CHECK(level BETWEEN 0 AND 2),
        influence INTEGER NOT NULL DEFAULT 0 CHECK(influence BETWEEN 0 AND 4294967295),
        credits INTEGER NOT NULL DEFAULT 0 CHECK(credits BETWEEN 0 AND 4294967295),
        gold INTEGER NOT NULL DEFAULT 0 CHECK(gold BETWEEN 0 AND 4294967295),
        revision INTEGER NOT NULL DEFAULT 1,next_item INTEGER NOT NULL DEFAULT 1073741824)''')
    db.execute('''CREATE TABLE IF NOT EXISTS clan_members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,account TEXT NOT NULL UNIQUE,clan_id INTEGER NOT NULL,
        permissions INTEGER NOT NULL,title INTEGER NOT NULL DEFAULT 0,contribution INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(clan_id) REFERENCES clans(id))''')
    db.execute('''CREATE TABLE IF NOT EXISTS clan_invitations (
        account TEXT PRIMARY KEY,clan_id INTEGER NOT NULL,inviter TEXT NOT NULL,expires REAL NOT NULL,
        FOREIGN KEY(clan_id) REFERENCES clans(id))''')
    db.execute('''CREATE TABLE IF NOT EXISTS clan_items (
        clan_id INTEGER NOT NULL,kind INTEGER NOT NULL CHECK(kind IN (1,2)),instance_id INTEGER NOT NULL,
        item_packet BLOB NOT NULL,PRIMARY KEY(clan_id,instance_id),FOREIGN KEY(clan_id) REFERENCES clans(id))''')
    db.execute('''CREATE TABLE IF NOT EXISTS clan_ledger (
        id INTEGER PRIMARY KEY AUTOINCREMENT,clan_id INTEGER NOT NULL,account TEXT NOT NULL,
        operation TEXT NOT NULL,detail TEXT NOT NULL,created REAL NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS clan_crystals (
        clan_id INTEGER PRIMARY KEY,amount INTEGER NOT NULL CHECK(amount BETWEEN 0 AND 4294967295))''')
    db.execute('''CREATE TABLE IF NOT EXISTS crystal_wallets (
        account TEXT PRIMARY KEY,amount INTEGER NOT NULL CHECK(amount BETWEEN 0 AND 4294967295))''')


def available(db):return bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='clans'").fetchone())


def membership(db,account):
    if not available(db):return None
    row=db.execute('''SELECT c.id,c.name,c.leader,c.level,c.influence,c.credits,c.gold,c.revision,
        m.id,m.permissions,m.title,m.contribution FROM clans c JOIN clan_members m ON c.id=m.clan_id
        WHERE m.account=?''',(account,)).fetchone()
    if row is None:return None
    keys=('id','name','leader','level','influence','credits','gold','revision','member_id','permissions','title','contribution')
    result=dict(zip(keys,row));result['name']=bytes(result['name']);result['capacity']=CAPACITY
    crystals=db.execute('SELECT amount FROM clan_crystals WHERE clan_id=?',(result['id'],)).fetchone() if db.execute("SELECT 1 FROM sqlite_master WHERE name='clan_crystals'").fetchone() else None
    result['crystals']=crystals[0] if crystals else 0
    result['leader_name']=character(db,result['leader'])
    from .clan_benefits import crest_id
    result['crest_id']=crest_id(db,result['id'])
    return result


def character(db,account):
    row=db.execute('SELECT name FROM characters WHERE account=? ORDER BY slot LIMIT 1',(account,)).fetchone()
    if row is None:raise ClanRejected('Персонаж не найден')
    return bytes(row[0])


def target_account(db,name):
    if not name or not name.isalnum():raise ClanRejected('Некорректное имя персонажа')
    row=db.execute('SELECT account FROM characters WHERE name_key=?',(name.decode('ascii').lower(),)).fetchone()
    if row is None:raise ClanRejected('Персонаж не найден')
    return row[0]


def level(db,account):
    row=db.execute('SELECT human,pet_packet FROM owned_pets WHERE account=? AND pet_id=1',(account,)).fetchone()
    return decode_pet_info(row[1],human_equipment=bool(row[0])).fields['0x8c4aef'] if row else 0


def require(db,account,right=0,leader=False):
    clan=membership(db,account)
    if clan is None:raise ClanRejected('Вы не состоите в клане')
    if leader and clan['leader']!=account:raise ClanRejected('Действие доступно только лидеру клана')
    if right and clan['leader']!=account and clan['permissions']&right!=right:
        raise ClanRejected('Недостаточно клановых полномочий')
    return clan


def require_roster_change(db,clan_id):
    """Registered assault squads keep their authoritative clan membership."""
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='warfare_clan_locks'").fetchone():
        if db.execute('SELECT 1 FROM warfare_clan_locks WHERE clan_id=?',(clan_id,)).fetchone():
            raise ClanRejected('Состав клана закреплён до завершения штурма')


def record(db,clan,account,operation,detail=''):
    db.execute('INSERT INTO clan_ledger(clan_id,account,operation,detail,created) VALUES (?,?,?,?,?)',
               (clan,account,operation,str(detail),time.time()))
    db.execute('UPDATE clans SET revision=revision+1 WHERE id=?',(clan,))


class ClansStore:
    def __init__(self,path,*,clock=time.time):
        self.path=path;self.clock=clock
        WarehouseStore(path)
        with closing(connect(path)) as db,db:
            db.execute('BEGIN IMMEDIATE');schema(db)
            from .social_completion import schema as social_schema
            social_schema(db)

    def info(self,account):
        with closing(connect(self.path)) as db:
            db.execute('BEGIN');return membership(db,account)

    def snapshot(self,account,online=()):
        with closing(connect(self.path)) as db:
            db.execute('BEGIN');clan=membership(db,account)
            if clan is None:return None,()
            members=[]
            for mid,owner,rights,title,contribution in db.execute('''SELECT id,account,permissions,title,contribution
                FROM clan_members WHERE clan_id=? ORDER BY id''',(clan['id'],)):
                members.append(dict(id=mid,name=character(db,owner),level=min(255,level(db,owner)),
                    online=owner in online,leader=owner==clan['leader'],permissions=rights,title=title,contribution=contribution))
            return clan,tuple(members)

    def create(self,account,name):
        try:text=name.decode('cp1251')
        except (UnicodeError,AttributeError):raise ClanRejected('Некорректное название клана')
        if not 3<=len(name)<=32 or text!=text.strip() or any(unicodedata.category(c)[0]=='C' for c in text):
            raise ClanRejected('Название клана должно содержать от 3 до 32 символов')
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE');character(db,account)
            from .social_completion import require_join
            require_join(db,account,now=self.clock())
            if membership(db,account):raise ClanRejected('Вы уже состоите в клане')
            if level(db,account)<4:raise ClanRejected('Для создания клана нужен командир 4 уровня')
            key=unicodedata.normalize('NFKC',text).casefold()
            if db.execute('SELECT 1 FROM clans WHERE name_key=?',(key,)).fetchone():raise ClanRejected('Название клана уже занято')
            clan=db.execute('INSERT INTO clans(name,name_key,leader) VALUES (?,?,?)',(name,key,account)).lastrowid
            if clan>0xffffffff:raise ClanRejected('Clan ID exhausted')
            db.execute('INSERT INTO clan_members(account,clan_id,permissions) VALUES (?,?,?)',(account,clan,KNOWN_RIGHTS))
            db.execute('DELETE FROM clan_invitations WHERE account=?',(account,))
            record(db,clan,account,'create')
        return clan

    def invite(self,account,name,now=None):
        now=self.clock() if now is None else now
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE');clan=require(db,account,INVITE)
            target=target_account(db,name)
            if membership(db,target):raise ClanRejected('Игрок уже состоит в клане')
            from .social_completion import require_join
            require_join(db,target,now=now)
            if db.execute('SELECT count(*) FROM clan_members WHERE clan_id=?',(clan['id'],)).fetchone()[0]>=MEMBER_LIMITS[clan['level']]:
                raise ClanRejected('В клане нет свободных мест')
            old=db.execute('SELECT expires FROM clan_invitations WHERE account=?',(target,)).fetchone()
            if old and old[0]>now:raise ClanRejected('У игрока уже есть действующее приглашение')
            db.execute('INSERT OR REPLACE INTO clan_invitations VALUES (?,?,?,?)',(target,clan['id'],account,now+300))
            record(db,clan['id'],account,'invite',name.decode('ascii'))
            return target,clan

    def accept(self,account,decision,now=None):
        if type(decision) is not int or decision not in (0,1):raise ClanRejected('Некорректный ответ на приглашение')
        now=self.clock() if now is None else now
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT clan_id,inviter,expires FROM clan_invitations WHERE account=?',(account,)).fetchone()
            if row is None:
                from .social_completion import join_replay
                member=membership(db,account)
                if decision and member and join_replay(db,account,member['id']):return member['id']
                raise ClanRejected('Приглашение больше не действует')
            cid,inviter,expires=row
            if not decision:
                db.execute('DELETE FROM clan_invitations WHERE account=?',(account,));return 0
            if expires<=now:raise ClanRejected('Срок приглашения истёк')
            clan=require(db,inviter,INVITE)
            if clan['id']!=cid:raise ClanRejected('Приглашение больше не действует')
            require_roster_change(db,cid)
            if membership(db,account):raise ClanRejected('Вы уже состоите в клане')
            from .social_completion import require_join,joined
            require_join(db,account,now=now)
            if db.execute('SELECT count(*) FROM clan_members WHERE clan_id=?',(cid,)).fetchone()[0]>=MEMBER_LIMITS[clan['level']]:
                raise ClanRejected('В клане нет свободных мест')
            mid=db.execute('INSERT INTO clan_members(account,clan_id,permissions) VALUES (?,?,?)',(account,cid,DEFAULT_RIGHTS)).lastrowid
            if mid>0xffffffff:raise ClanRejected('Clan member ID exhausted')
            db.execute('DELETE FROM clan_invitations WHERE account=?',(account,))
            record(db,cid,account,'join');joined(db,account,cid,inviter,expires);return cid

    def permissions(self,account,member_id,rights,title):
        # Title255 is the client's "no title" sentinel; all native byte titles
        # are presentation only and never turn a member into the founder.
        if type(rights) is not int or rights<0 or rights&~KNOWN_RIGHTS:raise ClanRejected('Неизвестные полномочия')
        if type(title) is not int or not 0<=title<=255:raise ClanRejected('Некорректная должность')
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE');clan=require(db,account,leader=True)
            row=db.execute('SELECT account FROM clan_members WHERE id=? AND clan_id=?',(member_id,clan['id'])).fetchone()
            if row is None:raise ClanRejected('Участник не найден')
            if row[0]==account:raise ClanRejected('Права лидера нельзя изменить')
            db.execute('UPDATE clan_members SET permissions=?,title=? WHERE id=?',(rights,title,member_id))
            db.execute('DELETE FROM clan_invitations WHERE inviter=?',(row[0],))
            record(db,clan['id'],account,'permissions',f'{member_id}:{rights}:{title}')

    def remove(self,account,name=None):
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE');clan=require(db,account,KICK if name else 0)
            require_roster_change(db,clan['id'])
            target=target_account(db,name) if name else account
            member=membership(db,target)
            if member is None or member['id']!=clan['id']:raise ClanRejected('Игрок не состоит в вашем клане')
            if target==clan['leader']:raise ClanRejected('Перед выходом передайте руководство кланом')
            db.execute('DELETE FROM clan_members WHERE account=?',(target,))
            db.execute('DELETE FROM clan_invitations WHERE inviter=?',(target,))
            record(db,clan['id'],account,'kick' if name else 'leave',target)
            from .social_completion import departed
            departed(db,target,clan['id'],'kick' if name else 'leave',now=self.clock())
            return target

    def transfer_leader(self,account,name):
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE');clan=require(db,account,leader=True);target=target_account(db,name)
            member=membership(db,target)
            if member is None or member['id']!=clan['id'] or target==account:raise ClanRejected('Выберите другого участника вашего клана')
            db.execute('UPDATE clans SET leader=? WHERE id=?',(target,clan['id']))
            db.execute('UPDATE clan_members SET permissions=? WHERE account=?',(KNOWN_RIGHTS,target))
            db.execute('UPDATE clan_members SET permissions=? WHERE account=?',(DEFAULT_RIGHTS,account))
            db.execute('DELETE FROM clan_invitations WHERE clan_id=?',(clan['id'],))
            record(db,clan['id'],account,'leader',target)

    def dissolve(self,account,clan_id):
        # Explicit emulator policy: only an empty, single-member clan may be
        # dissolved. Never destroy another member's shared property implicitly.
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE');clan=require(db,account,leader=True)
            if clan_id!=clan['id']:raise ClanRejected('Некорректный клан')
            require_roster_change(db,clan_id)
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='alliance_members'").fetchone():
                from .alliances import configured_member
                if configured_member(db,clan_id):raise ClanRejected('Перед роспуском выйдите из альянса')
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='territory_claims'").fetchone():
                if db.execute('SELECT 1 FROM territory_claims WHERE owner_clan=?',(clan_id,)).fetchone():
                    raise ClanRejected('Перед роспуском освободите принадлежащие клану базы')
            if db.execute('SELECT count(*) FROM clan_members WHERE clan_id=?',(clan_id,)).fetchone()[0]!=1:
                raise ClanRejected('Перед роспуском из клана должны выйти остальные участники')
            from .mine_claims import configured_owner
            if configured_owner(db,clan_id):
                raise ClanRejected('Перед роспуском освободите принадлежащие клану блокпосты')
            if clan['credits'] or clan['gold'] or clan['crystals'] or db.execute('SELECT 1 FROM clan_items WHERE clan_id=?',(clan_id,)).fetchone():
                raise ClanRejected('Перед роспуском заберите клановые активы')
            record(db,clan_id,account,'dissolve')
            from .social_completion import departed
            departed(db,account,clan_id,'dissolve',now=self.clock())
            db.execute('DELETE FROM clan_invitations WHERE clan_id=?',(clan_id,))
            db.execute('DELETE FROM clan_members WHERE clan_id=?',(clan_id,))
            db.execute('DELETE FROM clans WHERE id=?',(clan_id,))

    def upgrade(self,account,action):
        if action!=1:raise ClanRejected('Неизвестная операция клана')
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE');clan=require(db,account,UPGRADE)
            if clan['level']>=2:raise ClanRejected('Достигнут максимальный уровень клана')
            credits,influence=((15000,5000),(25000,10000))[clan['level']]
            wallet=db.execute('SELECT credits FROM wallets WHERE account=?',(account,)).fetchone()
            if not wallet or wallet[0]<credits or clan['influence']<influence:raise ClanRejected('Недостаточно кредитов или влияния')
            db.execute('UPDATE wallets SET credits=credits-? WHERE account=?',(credits,account))
            db.execute('UPDATE clans SET level=level+1,influence=influence-? WHERE id=?',(influence,clan['id']))
            record(db,clan['id'],account,'upgrade',influence)

    @staticmethod
    def _items(db,cid,kind):
        items={}
        for key,packet in db.execute('SELECT instance_id,item_packet FROM clan_items WHERE clan_id=? AND kind=? ORDER BY instance_id',(cid,kind)):
            owner,records,_=decode_item_list(packet)
            if owner or len(records)!=1 or records[0].instance_id!=key or records[0].equipped or records[0].slot or records[0].count<1:
                raise ClanRejected('Invalid clan item state')
            items[key]=records[0]
        return items

    def items(self,account,kind):
        if kind not in (1,2):raise ClanRejected('Unknown clan warehouse')
        with closing(connect(self.path)) as db:
            db.execute('BEGIN');clan=require(db,account,VIEW_WAREHOUSE if kind==1 else VIEW_SAFE)
            return tuple(self._items(db,clan['id'],kind).values())

    def warehouse_packets(self,account,kind):
        from .protocol.warehouse import encode_warehouse_list,warehouse_item_from_inventory,WarehouseItem
        with closing(connect(self.path)) as db:
            db.execute('BEGIN');clan=require(db,account,VIEW_WAREHOUSE if kind==1 else VIEW_SAFE)
            items=[warehouse_item_from_inventory(i) for i in self._items(db,clan['id'],kind).values()]
            if kind==2:
                items.extend(WarehouseItem(key,template,clan[column],0,0,0) for key,(column,template,_) in MONEY_IDS.items() if clan[column])
            return (encode_warehouse_list(kind,1,0,items),)

    def exchange(self,account,pet_id,kind,*,deposits=(),withdrawals=()):
        if kind not in (1,2):raise ClanRejected('Unknown clan warehouse')
        selections=[]
        for pairs in (deposits,withdrawals):
            chosen={}
            for key,count in pairs:
                if type(key) is not int or not 0<key<=0xffffffff or type(count) is not int or not 0<count<=0xffffffff or key in chosen:
                    raise ClanRejected('Invalid or repeated item selection')
                chosen[key]=count
            selections.append(chosen)
        deposits,withdrawals=selections
        if deposits.keys()&withdrawals.keys():raise ClanRejected('An item cannot move both ways')
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE');clan=require(db,account,VIEW_WAREHOUSE if kind==1 else VIEW_SAFE)
            if withdrawals and kind==1:require(db,account,WITHDRAW_WAREHOUSE)
            row=db.execute('SELECT human,pet_packet,inventory_packet FROM owned_pets WHERE account=? AND pet_id=?',(account,pet_id)).fetchone()
            if row is None or OwnedPetStore.validate(row[1],row[2],bool(row[0]))!=pet_id:raise ClanRejected('Owned mercenary required')
            # Server-issued virtual wallet/safe instances travel through the
            # original6B arrays. They never become physical inventory items.
            money=[]
            if kind==2:
                for key,(column,template,right) in MONEY_IDS.items():
                    give=deposits.pop(key,0);take=withdrawals.pop(key,0)
                    if not (give or take):continue
                    if take:require(db,account,right)
                    if column=='crystals':
                        wallet=db.execute('SELECT amount FROM crystal_wallets WHERE account=?',(account,)).fetchone()
                        balance=wallet[0] if wallet else 0
                    else:
                        wallet=db.execute(f'SELECT {column} FROM wallets WHERE account=?',(account,)).fetchone()
                        if not wallet:raise ClanRejected('Кошелёк не найден')
                        balance=wallet[0]
                    personal=balance-give+take;shared=clan[column]+give-take
                    if not 0<=personal<=0xffffffff or not 0<=shared<=0xffffffff:
                        raise ClanRejected('Недостаточно средств или переполнение баланса')
                    money.append((column,personal,shared,give,take))
            _,original,unknown=decode_item_list(row[2]);inventory={i.instance_id:i for i in original}
            if len(inventory)!=len(original):raise ClanRejected('Duplicate inventory item IDs')
            warehouse=self._items(db,clan['id'],kind)
            initial_count=len(warehouse)
            for selection,source in ((deposits,inventory),(withdrawals,warehouse)):
                for key,count in selection.items():
                    item=source.get(key)
                    if item is None:raise ClanRejected('Selected item is not in the owned source')
                    if count>item.count:raise ClanRejected('Insufficient item quantity')
                    if item.equipped or item.slot:raise ClanRejected('Unequip item before transferring')
                    from .item_boosters import nontransferable
                    if nontransferable(item.template_id):raise ClanRejected('Бустеры нельзя продавать и передавать')
                    if item.unknown_bytes_02[2] or item.unknown_bytes_02[3] or item.optional_u32 is not None:
                        raise ClanRejected('Помеченные, арендованные и временные предметы нельзя передавать клану')
                    if kind==2:
                        right={30:WITHDRAW_UPGRADES}.get(item.template_id)
                        if right is None:raise ClanRejected('В клановом сейфе доступны только Upgrade Kit')
                        if source is warehouse:require(db,account,right)
            seen=set(WarehouseStore._read(db,account))
            for packet, in db.execute('SELECT inventory_packet FROM owned_pets WHERE account=?',(account,)):
                for i in decode_item_list(packet)[1]:
                    if i.instance_id in seen:raise ClanRejected('Item ID exists in multiple locations')
                    seen.add(i.instance_id)
            sequence=db.execute('SELECT next_id FROM item_sequences WHERE account=?',(account,)).fetchone()
            next_personal=max(max(seen,default=0)+1,sequence[0] if sequence else 1)
            next_shared=db.execute('SELECT next_item FROM clans WHERE id=?',(clan['id'],)).fetchone()[0]
            for selection,source,destination in ((withdrawals,warehouse,inventory),(deposits,inventory,warehouse)):
                for key,count in selection.items():
                    item=source[key]
                    new=next_shared if source is inventory else next_personal
                    if new>=0xffff0000:raise ClanRejected('Item ID space exhausted')
                    if source is inventory:next_shared+=1
                    else:next_personal+=1
                    if count==item.count:source.pop(key)
                    else:source[key]=replace(item,unknown_u32_01=item.count-count)
                    destination[new]=replace(item,instance_id=new,unknown_u32_01=count)
            warehouse={i.instance_id:i for i in merge_stacks(warehouse.values())}
            inventory={i.instance_id:i for i in merge_stacks(inventory.values())}
            from .warehouse_completion import clan_capacity
            if len(warehouse)>max(initial_count,clan_capacity(db,clan['id'],kind)):raise ClanRejected('Warehouse capacity exceeded')
            validate_capacity(original,inventory,error=ClanRejected)
            updated=encode_item_list(pet_id,tuple(inventory.values()),unknown)
            from .protocol.warehouse import encode_warehouse_snapshot
            encode_warehouse_snapshot(kind,warehouse.values())
            db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=?',(updated,account,pet_id))
            db.execute('DELETE FROM clan_items WHERE clan_id=? AND kind=?',(clan['id'],kind))
            db.executemany('INSERT INTO clan_items VALUES (?,?,?,?)',[(clan['id'],kind,k,encode_item_list(0,(i,))) for k,i in warehouse.items()])
            db.execute('INSERT INTO item_sequences VALUES (?,?) ON CONFLICT(account) DO UPDATE SET next_id=excluded.next_id',(account,next_personal))
            db.execute('UPDATE clans SET next_item=? WHERE id=?',(next_shared,clan['id']))
            for column,personal,shared,give,take in money:
                if column=='crystals':
                    db.execute('''INSERT INTO crystal_wallets VALUES (?,?) ON CONFLICT(account)
                        DO UPDATE SET amount=excluded.amount''',(account,personal))
                    db.execute('''INSERT INTO clan_crystals VALUES (?,?) ON CONFLICT(clan_id)
                        DO UPDATE SET amount=excluded.amount''',(clan['id'],shared))
                else:
                    db.execute(f'UPDATE wallets SET {column}=? WHERE account=?',(personal,account))
                    db.execute(f'UPDATE clans SET {column}=? WHERE id=?',(shared,clan['id']))
                record(db,clan['id'],account,'money',f'{column}:{give}:{take}')
            record(db,clan['id'],account,'items',f'{kind}:{list(deposits.items())}:{list(withdrawals.items())}')
            return updated,tuple(warehouse.values())


def settle_influence(db,account,experience,*,identity=None,city_coefficient=1,now=None):
    """Durable XP contribution/achievement hook in the caller's reward transaction.

    Pass the authoritative match identity, city influence coefficient and reward
    timestamp for complete benefits. The old three-argument call keeps its
    legacy return/calculation and relies on its enclosing battle receipt; it
    never invents an identity or backfills old rewards.
    """
    if identity is not None:
        from .clan_benefits import settle_experience
        from .achievements import influence_received
        receipt=settle_experience(db,account,identity,experience,
            city_coefficient=city_coefficient,now=now)
        influence_received(db,account,'xp:'+identity,receipt['amount'])
        return receipt
    if city_coefficient!=1 or now is not None:
        raise ValueError('Complete clan benefits require the authoritative reward identity')
    clan=membership(db,account)
    amount=sum(experience.values())//20
    if clan is None or amount<=0:return
    amount=min(amount,0xffffffff-clan['influence'],0xffffffff-clan['contribution'])
    db.execute('UPDATE clans SET influence=influence+?,revision=revision+1 WHERE id=?',(amount,clan['id']))
    db.execute('UPDATE clan_members SET contribution=contribution+? WHERE account=?',(amount,account))


def project_assets(db,account,assets):
    clan=membership(db,account)
    if clan and (clan['leader']==account or clan['permissions']&VIEW_SAFE):
        return replace(assets,unknown_u32_08=clan['credits'],unknown_u32_09=clan['gold'])
    return replace(assets,unknown_u32_08=0,unknown_u32_09=0)


def append_money(packet,assets):
    """Native918390 copies city soldier inventory into its personal kind5 cache.

    Currency instances are a client projection, never persisted as items. The
    native6A consumer ignores kind5, so currency sources must be real30 records.
    """
    owner,items,unknown=decode_item_list(packet)
    if owner!=1:return packet
    physical=tuple(i for i in items if i.instance_id not in MONEY_IDS)
    def amount(column):return getattr(assets,'spectra_crystals' if column=='crystals' else column)
    money=tuple(ItemRecord(key,template,b'\0\0',amount(column),0,0,(0,0,0),bytes(4),None,bytes(3))
        for key,(column,template,_) in MONEY_IDS.items() if column!='crystals' or amount(column))
    return encode_item_list(owner,(*physical,*money),unknown)


def project_inventory(path,account,packet):
    if packet[:1]!=b'\x30' or int.from_bytes(packet[1:5],'little')!=1:return packet
    with closing(connect(path)) as db:
        db.execute('BEGIN');clan=membership(db,account)
        if clan is None:return packet
        row=db.execute('SELECT credits,gold FROM wallets WHERE account=?',(account,)).fetchone()
        if row is None:return packet
        from .protocol.asset_count import AssetCount
        crystals=db.execute('SELECT amount FROM crystal_wallets WHERE account=?',(account,)).fetchone() if db.execute("SELECT 1 FROM sqlite_master WHERE name='crystal_wallets'").fetchone() else None
        return append_money(packet,AssetCount(*row,spectra_crystals=crystals[0] if crystals else 0))


def project_asset_packet(path,account,packet):
    from .protocol.asset_count import decode_asset_count,encode_asset_count
    with closing(connect(path)) as db:
        return encode_asset_count(project_assets(db,account,decode_asset_count(packet)))
