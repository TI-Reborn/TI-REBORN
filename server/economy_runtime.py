"""Shared city economy, offline timers and private inventory refreshes."""
from contextlib import closing
import hashlib
import time

from tio.db_transaction import connect,transaction
from tio.bank_economy import BankStore,expire_marks,project_marks
from tio.private_shops import PrivateShopStore
from tio.sc_auction import SCAuctionStore
from tio.owned_pets import OwnedPetStore
from tio.warehouse import WarehouseStore
from tio.protocol.warehouse import encode_private_warehouse_snapshot
from .private_market import PrivateMarketSession


def private_command(packet):
    if packet[:1]!=b'\x21':return False
    from tio.protocol.chat import decode_send
    try:_,text,_=decode_send(packet)
    except ValueError:return False
    words=text.strip().casefold().split()
    return bool(words and words[0] in ('!bank','!sc','!base','!assault'))


def city_idle(session):
    router=getattr(session,'router',None);hub=getattr(router,'team_arena',None)
    character=getattr(session,'probe_character_id',None)
    locations=getattr(session,'locations',None)
    return bool(character is not None and locations and locations.current(session.account) is not None
        and not locations.travelling(session.account)
        and not (hub and (hub.busy(session) or hub.retained(session.account)))
        and not session.arena._fields
        and not any(character in room.members for room in session.arena.rooms.snapshot())
        and not session.survival.searching(character))


def busy_accounts(router,db=None):
    """Caller holds hub.lock so scene birth cannot race an item return."""
    hub=router.team_arena;busy=set(hub.private)
    busy.update(account for account in hub.account_owners if hub.retained(account))
    # Retained journals include results/recovery and process-crash leases.
    if db is not None:
        for table in ('battle_checkpoint_members','battle_settlement_jobs'):
            if db.execute('SELECT 1 FROM sqlite_master WHERE name=?',(table,)).fetchone():
                busy.update(r[0] for r in db.execute('SELECT account FROM '+table))
    with router.lock:sessions=tuple(router.active_accounts.values())
    for session in sessions:
        if getattr(session,'account',None) and getattr(session,'probe_character_id',None) is not None and not city_idle(session):
            busy.add(session.account)
    return busy


def inventory_snapshot(path,account):
    """Canonical SQL snapshots; outward marks are projected at serialization."""
    roster=OwnedPetStore(path).list(account)
    warehouse=WarehouseStore(path).items(account)
    return tuple(p for _,pet,inventory in roster for p in (pet,inventory))+tuple(encode_private_warehouse_snapshot(warehouse))


def project_packet(path,account,packet):
    if packet[:1] in (b'\x30',b'\x6a'):
        with closing(connect(path)) as db:return project_marks(db,account,packet)
    if packet[:2]==b'\xc8\x39':
        # Read fresh paid Gold and securities after a successful Gold debit.
        from tio.wallets import WalletStore
        from tio.protocol.asset_count import encode_asset_count
        return encode_asset_count(WalletStore(path).ensure(account))
    return packet


class SharedEconomy:
    def __init__(self,path,*,clock=time.monotonic):
        self.path=path;self.clock=clock;self.next_tick=0
        self.next_clan_tick=clock()+60
        self.shops=PrivateShopStore(path);self.auction=SCAuctionStore(path);self.bank=BankStore(path)

    def session(self,session):
        return PrivateMarketSession(self.shops,self.auction,session.account,character_id=session.probe_character_id)

    def bank_session(self,session):
        from .bank_gameplay import BankGameSession
        return BankGameSession(self.path,session.account)

    def tick(self,router):
        if self.clock()<self.next_tick:return
        self.next_tick=self.clock()+.5
        self.auction.tick()
        with router.team_arena.lock,transaction(self.path) as db:
            expire_marks(db,busy=busy_accounts(router,db))
            if self.clock()>=self.next_clan_tick:
                from .clan_gameplay import maintenance
                maintenance(db)
                self.next_clan_tick=self.clock()+60


def refresh_inventory(session,*,force=False):
    if not city_idle(session):return ()
    packets=inventory_snapshot(session.database,session.account)
    digest=hashlib.sha256(b''.join(packets)).digest()
    if not force and getattr(session,'_economy_inventory_digest',None)==digest:return ()
    session._economy_inventory_digest=digest
    return packets


def handle_private(session,packet):
    """Consume private commands before presence, logging or any broadcast."""
    if not private_command(packet):return None
    from tio.protocol.chat import decode_send,encode_system_message
    from tio.protocol.system_message import encode_shop_error
    _,text,_=decode_send(packet)
    hub=session.router.team_arena
    try:
        with hub.lock,transaction(session.database) as db:
            allowed=city_idle(session)
            blocked=busy_accounts(session.router,db)
            if text.strip().casefold().split(maxsplit=1)[:1]==['!assault']:
                from .assault_public import command
                return command(db,session.account,text)
            if text.split(maxsplit=1)[:1]==['!base']:
                from .clan_gameplay import command
                return command(db,session.account,text,city_idle=allowed)
            if text.split(maxsplit=1)[:1]==['!bank']:
                result=session.bank_session.handle(packet,city_idle=allowed,busy=blocked)
                # Peers collect canonical SQL snapshots on their own city poll.
                # No other owner's packets enter this connection's reply.
                if result.changed_accounts:
                    with session.router.lock:
                        for peer in session.router.active_accounts.values():
                            if peer.account in result.changed_accounts:
                                peer._economy_inventory_digest=None
                return result.packets
            if text.split(maxsplit=1)[:1]!=['!sc']:
                raise ValueError('Команды вводятся как !bank, !sc, !base и !assault')
            lines=session.private_market.command(text,allow_mutation=allowed)
            replies=tuple(encode_system_message(4,b'SC',line) for line in lines[-200:])
            if allowed:replies+=session.private_market.balances()+refresh_inventory(session,force=True)
            return replies
    except ValueError as error:
        return (encode_shop_error(str(error)),)
