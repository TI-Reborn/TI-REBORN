"""Native alliance delivery from authenticated, shared SQLite clan authority.

No crest identifier is synthesized from an alliance ID. Wire influence is
bounded to u32; sorting and stored spendable influence keep the exact sum.
"""
from contextlib import closing
from pathlib import Path
import unicodedata

from tio.db_transaction import connect
from tio.alliances import AlliancesStore
from tio.clans import membership,character,level as character_level,MEMBER_LIMITS
from tio.clan_benefits import crest_id
from tio.protocol.alliances import (decode_request,encode_info,encode_invitation,encode_ratings,
    AllianceInfo,AllianceClan,AllianceMember)
from tio.protocol.system_message import encode_shop_error


def store(session):
    current=getattr(session,'alliances_store',None)
    if current is None:session.alliances_store=current=AlliancesStore(session.database)
    return current


def enqueue(presence,session,*packets):
    from .clan_service import enqueue as put
    put(presence,session,*packets)


def projection(db,header,clans=(),online=()):
    if header is None:return AllianceInfo(0,b'',0,0,0,0)
    online=set(online);rows=[]
    for clan in clans:
        members=tuple(AllianceMember(character(db,account),int(account in online),
            min(255,character_level(db,account))) for (account,) in db.execute(
                'SELECT account FROM clan_members WHERE clan_id=? ORDER BY id',(clan['id'],)))
        rows.append(AllianceClan(clan['id'],clan['name'],clan['level'],clan['influence'],
                                character(db,clan['leader']),members,crest_id=crest_id(db,clan['id'])))
    return AllianceInfo(header['id'],header['name'],header['level'],header['leading_clan'],
        # AF0D's boolean is ABI-proven, but its gameplay meaning is not yet
        # established. Do not confuse it with our pending-dissolution state.
        min(0xffffffff,header['influence']),0,tuple(rows),crest_id=header.get('crest_id',0))


def sync(presence,session):
    current=store(session)
    with presence.lock:online=tuple(s.account for s in presence.players)
    with closing(connect(session.database)) as db:
        db.execute('BEGIN')
        header,clans=current.snapshot(session.account,db=db)
        packet=encode_info(projection(db,header,clans,online))
        signature=(packet,header['revision'] if header else 0)
        if signature!=getattr(session,'alliances_signature',None):
            enqueue(presence,session,packet);session.alliances_signature=signature
        clan=membership(db,session.account);invitation=None;token=None
        # A clan invitation is shown only to that clan's current leader.
        if clan and clan['leader']==session.account:
            row=db.execute('SELECT alliance_id,inviter,expires FROM alliance_invites WHERE target_clan=?',
                           (clan['id'],)).fetchone()
            if row and row[2]>current.clock():
                aid,inviter,expiry=row;inviting,cohort=current.snapshot(inviter,db=db)
                if (inviting and inviting['id']==aid and inviting['state']=='active' and
                        inviting['leader']==inviter and len(cohort)<inviting['level']+1):
                    invitation=encode_invitation(character(db,inviter),inviting['name'])
                    token=(row,inviting['revision'],inviting['leading_clan'],inviting['leader'],len(cohort),invitation)
        if invitation and token!=getattr(session,'alliances_invitation',None):enqueue(presence,session,invitation)
        session.alliances_invitation=token


def notify(presence,source):
    # Copy sessions before SQLite reads; never nest hub/Presence locks.
    with presence.lock:sessions=tuple(presence.players)
    from .clan_service import sync as sync_clan
    identity=Path(source.database).resolve()
    for session in sessions:
        if getattr(session,'owned_pet_probe',False) and Path(session.database).resolve()==identity:
            sync_clan(presence,session)
    if source not in sessions:sync_clan(presence,source)


def require_city(session):
    team=getattr(getattr(session,'router',None),'team_arena',None)
    busy=(bool(team and team.busy(session)) or session.survival.searching(session.probe_character_id) or
          any(session.probe_character_id in room.members for room in session.arena.rooms.snapshot()))
    if busy or not session.owned_pet_probe or session.locations and session.locations.current(session.account) is None:
        raise ValueError('Операции альянса доступны в городе вне боя и поиска')


def target_clan(session,name):
    try:key=unicodedata.normalize('NFKC',name.decode('cp1251')).casefold()
    except UnicodeError:raise ValueError('Некорректное название клана')
    with closing(connect(session.database)) as db:
        row=db.execute('SELECT id FROM clans WHERE name_key=?',(key,)).fetchone()
        if row is None:raise ValueError('Клан не найден')
        return row[0]


def ratings(session):
    from tio.clan_ratings import alliances
    with closing(connect(session.database)) as db:
        db.execute('BEGIN');rows=[]
        for item in alliances(db):
            cohort=[]
            for cid in item['clans']:
                clan=db.execute('SELECT name,leader,level,influence FROM clans WHERE id=?',(cid,)).fetchone()
                cohort.append(AllianceClan(cid,bytes(clan[0]),clan[2],clan[3],character(db,clan[1]),crest_id=crest_id(db,cid)))
            rows.append(AllianceInfo(item['id'],item['name'],item['level'],item['leading_clan'],
                min(0xffffffff,item['influence']),0,tuple(cohort),crest_id=item.get('crest_id',0)))
        return encode_ratings(rows)


def classic_ratings(session,packet):
    from tio.clan_ratings import clans
    from tio.alliances import alliance_for_clan
    from .assault_public import active_badge_places
    from tio.protocol.clan_ratings import decode_request as decode_rating,encode_ratings as encode_rating,ClanRating
    kind,selector=decode_rating(packet)
    if kind not in (0,1,2) or selector not in (0,1):raise ValueError('Некорректный раздел кланового рейтинга')
    with closing(connect(session.database)) as db:
        db.execute('BEGIN')
        badge_places=active_badge_places(db)
        # Both native page selectors render the second numeric column (row+214h).
        rows=tuple(ClanRating(id=r['id'],name=r['name'],leader=r['leader_name'],
            members=r['members'],capacity=MEMBER_LIMITS[r['level']],level=r['level'],
            influence=r['rating'] if selector else r['influence'],
            crest_id=crest_id(db,r['id']),alliance_crest_id=(alliance_for_clan(db,r['id']) or {}).get('crest_id',0),
            unknown_u32_3=badge_places.get(r['id'],0))
            for r in clans(db,offset=kind*100,limit=100,trueskill=bool(selector)))
        return encode_rating(kind,selector,rows)


def handle(presence,session,packet):
    if packet[:1]==b'\x82':
        try:enqueue(presence,session,classic_ratings(session,packet))
        except ValueError as exc:enqueue(presence,session,encode_shop_error(str(exc)[:180]))
        return True
    if packet[:1]!=b'\xaf':return False
    try:
        op,value=decode_request(packet)
        if op==14:
            enqueue(presence,session,ratings(session));return True
        require_city(session);current=store(session)
        if op==1:current.create(session.account,value)
        elif op==2:current.invite(session.account,target_clan(session,value))
        elif op==4:current.accept(session.account,value)
        elif op==8:current.upgrade(session.account)
        elif op==9:current.transfer_leading(session.account,value)
        elif op==10:current.leave(session.account)
        elif op==11:current.kick(session.account,value)
        elif op==12:
            # The native typed prompt sends AF0C for both choices. Retried
            # packets cannot prove a new intent to cancel; use the explicit
            # private name-confirmed adapter for cancellation.
            header=current.info(session.account)
            if header and header['state']=='dissolving':
                if header['leader']!=session.account:raise ValueError('Отмена доступна главе ведущего клана альянса')
                from tio.protocol.chat import encode_message
                enqueue(presence,session,encode_message(4,b'Clan',f"Для отмены роспуска: !clan alliancecancel {bytes(header['name']).decode('cp1251')}"))
            else:
                current.dissolve(session.account)
                header=current.info(session.account)
                from tio.protocol.chat import encode_message
                enqueue(presence,session,encode_message(4,b'Clan',f"Роспуск назначен на срок 3 суток. Отмена: !clan alliancecancel {bytes(header['name']).decode('cp1251')}"))
        notify(presence,session)
    except ValueError as exc:enqueue(presence,session,encode_shop_error(str(exc)[:180]))
    return True
