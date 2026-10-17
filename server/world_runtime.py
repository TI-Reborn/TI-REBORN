"""Shared admission snapshots and authenticated online prison heartbeats."""
from contextlib import closing,nullcontext
import secrets
import time

from tio.db_transaction import connect,transaction
from tio import world_completion as world


def admit(db,battle,*,now=None):
    if battle.get('kind') in ('tutorial','wager','contract'):return None
    town=battle.get('city_id')
    if town is None:return None
    for account,_,_ in battle['reward_roster'].values():world.require_travel(db,account)
    saved=world.freeze_city(db,battle['match_id'],town,now=now)
    battle['city_coefficients']=saved
    battle['field'].combat.city_kill_bonus=saved['kill_bonus']
    return saved


def require_unjailed(session):
    with closing(connect(session.database)) as db:world.require_travel(db,session.account)


def project_town(session,packet):
    """Attach native training schedule only to this account's current TownInfo."""
    if packet[:2]!=b'\xc8\x2d' or len(packet)<4:return packet
    town=int.from_bytes(packet[2:4],'little')
    hub=getattr(getattr(session,'router',None),'team_arena',None)
    locations=getattr(session,'locations',None)
    if town in (19,20,21,22) and locations is not None and locations.current(session.account)==town and hub is not None and hasattr(hub,'training_path'):
        with hub.lock:return hub.training_town_packet(town)
    return packet


def heartbeat(session,*,active=True,now=None):
    if not getattr(session,'database',None) or not getattr(session,'account',None):return ()
    with closing(connect(session.database)) as db:state=world.prison_state(db,session.account)
    if state is None or state['remaining']<=0:return ()
    if not hasattr(session,'_prison_token'):session._prison_token='session:'+secrets.token_hex(24)
    hub=getattr(getattr(session,'router',None),'team_arena',None)
    with hub.lock if hub else nullcontext(),transaction(session.database) as db:
        before=state;after=world.prison_online(db,session.account,session._prison_token,now=now,active=active)
    if not active:return ()
    if after['town_id']==before['town_id'] and getattr(session,'_prison_announced_town',None)==after['town_id']:return ()
    session._prison_announced_town=after['town_id']
    from tio.locations import town_packets
    return town_packets(after['town_id'],session.database)


def standings(session,packet):
    from tio.protocol.player_top100 import decode_request,encode_world_rows,SORTS
    from tio.protocol.system_message import encode_shop_error
    try:
        selector=decode_request(packet)
        now=time.monotonic()
        if now<getattr(session,'_world_standings_at',0):return ()
        session._world_standings_at=now+.25
        return (encode_world_rows(selector,world.player_top100(session.database,sort=SORTS[selector])),)
    except ValueError as error:return (encode_shop_error(str(error)),)
