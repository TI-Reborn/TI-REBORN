"""Clan delivery uses each authenticated session's own Presence queue."""
from contextlib import closing
import time
from tio.db_transaction import connect
from tio.clans import ClansStore,membership,character,VIEW_SAFE,project_inventory
from tio.protocol.clans import decode_request,encode_info,encode_members,encode_invitation,encode_join
from tio.protocol.warehouse import encode_warehouse_list
from tio.protocol.asset_count import encode_asset_count
from tio.protocol.system_message import encode_shop_error
from tio.wallets import WalletStore
from tio.owned_pets import OwnedPetStore

OPERATIONS=(0x52,0x53,0x58,0x5b,0x5d,0x5f,0x60,0x98,0x99,0x31)


def store(session):
    current=getattr(session,'clans_store',None)
    if current is None:session.clans_store=current=ClansStore(session.database)
    return current


def enqueue(presence,session,*packets):
    with presence.lock:
        queue=presence.messages.get(session)
        if queue is not None:
            for p in packets:
                if len(queue)<128:queue.append(p)


def sync(presence,session):
    current=store(session)
    with presence.lock:online=tuple(s.account for s in presence.players)
    clan,members=current.snapshot(session.account,online)
    signature=(encode_info(clan),b'\x57',encode_members(members))
    revision=clan['revision'] if clan else 0
    revision_changed = revision != getattr(session, 'clans_revision', None)
    if signature!=getattr(session,'clans_signature',None) or revision_changed:
        old=getattr(session,'clans_signature',None)
        session.clans_signature=signature
        session.clans_revision=revision
        enqueue(presence,session,*signature)
        # Remove the stale contents on exit or revoked viewing rights. Actual
        # authorized contents are fetched through the client's normal69 query.
        if old is not None:
            enqueue(presence,session,encode_warehouse_list(1,1,0,()),encode_warehouse_list(2,1,0,()))
        if clan:
            from tio.clans import VIEW_WAREHOUSE
            for kind,right in ((1,VIEW_WAREHOUSE),(2,VIEW_SAFE)):
                if clan['permissions'] & right:
                    packets = current.warehouse_packets(session.account, kind, include_marks=True)
                    enqueue(presence, session, *packets)
            assets=WalletStore(session.database).ensure(session.account)
            enqueue(presence,session,encode_asset_count(assets))
            if old is not None and revision_changed:
                from .economy_runtime import city_idle
                from .item_mark_service import listing
                if city_idle(session):
                    with closing(connect(session.database)) as db:
                        db.execute('BEGIN')
                        mark_list = listing(db, session.account, int(time.time()))
                    enqueue(presence, session, mark_list)
        elif old is not None:
            enqueue(presence,session,encode_asset_count(WalletStore(session.database).ensure(session.account)))
        team=getattr(getattr(session,'router',None),'team_arena',None)
        if not getattr(session.arena,'_fields',{}) and not (team and team.in_battle(session)):
            packet=OwnedPetStore(session.database).inventory(session.account,1)
            if packet:
                from tio.enhancement_limits import project_owned_inventory
                enqueue(presence,session,project_inventory(session.database,session.account,project_owned_inventory(session.database,session.account,packet)))
    with closing(connect(session.database)) as db:
        row=db.execute('SELECT clan_id,inviter,expires FROM clan_invitations WHERE account=?',(session.account,)).fetchone()
        invitation=None
        if row and row[2]>time.time():
            cid,inviter,expires=row
            inviting=membership(db,inviter)
            if inviting and inviting['id']==cid:
                invitation=encode_invitation(inviting['member_id'],character(db,inviter),inviting['name'])
        token=(row,invitation)
        if invitation and token!=getattr(session,'clans_invitation',None):enqueue(presence,session,invitation)
        session.clans_invitation=token
    from .alliance_service import sync as sync_alliance
    sync_alliance(presence,session)


def handle(presence,session,packet):
    if packet[:1]==b'\x59' or packet[:2]==b'\xaf\x06':
        try:
            from tio.protocol.clan_crests import decode_request as decode_crest_request,encode_content
            from tio.clan_benefits import crest_content
            request=decode_crest_request(packet)
            with closing(connect(session.database)) as db:
                bmp=crest_content(db,request.crest_id)
            enqueue(presence,session,encode_content(request.crest_id,bmp,request.kind))
        except ValueError as exc:enqueue(presence,session,encode_shop_error(str(exc)[:180]))
        return True
    if packet[:1] in (b'\xaf',b'\x82'):
        from .alliance_service import handle as handle_alliance
        return handle_alliance(presence,session,packet)
    if not packet or packet[0] not in OPERATIONS:return False
    try:
        if packet[0]==0x58:
            from tio.protocol.clan_crests import decode_upload
            op,args=0x58,(decode_upload(packet),)
        else:op,args=decode_request(packet)
        team=getattr(getattr(session,'router',None),'team_arena',None)
        busy=(bool(team and team.busy(session)) or session.survival.searching(session.probe_character_id) or
              any(session.probe_character_id in room.members for room in session.arena.rooms.snapshot()))
        if busy or not session.owned_pet_probe or session.locations and session.locations.current(session.account) is None:
            raise ValueError('Клановые операции доступны в городе вне боя и поиска')
        current=store(session)
        if op==0x52:cid=current.create(session.account,*args);enqueue(presence,session,encode_join(cid))
        elif op==0x53:current.dissolve(session.account,*args);enqueue(presence,session,encode_join(0))
        elif op==0x5b:current.invite(session.account,*args)
        elif op==0x5d:
            cid=current.accept(session.account,*args)
            if cid:enqueue(presence,session,encode_join(cid))
        elif op==0x5f:current.remove(session.account,*args)
        elif op==0x60:current.remove(session.account);enqueue(presence,session,encode_join(0))
        elif op==0x98:current.permissions(session.account,*args)
        elif op==0x99:current.transfer_leader(session.account,*args)
        elif op==0x31:
            current.upgrade(session.account,*args)
            enqueue(presence,session,encode_asset_count(WalletStore(session.database).ensure(session.account)))
        elif op==0x58:
            from uuid import uuid4
            from tio.clan_benefits import set_crest
            from tio.db_transaction import transaction
            from .economy_runtime import city_idle
            if not city_idle(session):raise ValueError('Установка значка доступна в городе вне боя и поиска')
            with transaction(session.database) as db:set_crest(db,session.account,args[0],'native-crest-'+uuid4().hex)
            enqueue(presence,session,encode_asset_count(WalletStore(session.database).ensure(session.account)))
        sync(presence,session)
    except ValueError as exc:enqueue(presence,session,encode_shop_error(str(exc)[:180]))
    return True
