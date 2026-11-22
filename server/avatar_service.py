"""Native avatar window; owner identity comes exclusively from the session."""
from tio.avatars import request,snapshot
from tio.protocol.system_message import encode_shop_error


def handle(presence,session,packet):
    if packet[:1]!=b'\xac':return False
    from .economy_runtime import city_idle
    hub=session.router.team_arena
    with hub.lock:
        try:replies=request(session.database,session.account,packet,allowed=city_idle(session))
        except ValueError as error:replies=(encode_shop_error(str(error)),)
    with presence.lock:
        if session in presence.messages:presence.messages[session].extend(replies)
    return True


def sync(presence,session):
    if session.database is None or not getattr(session,'owned_pet_probe',False):return
    if not getattr(session,'avatar_sync_needed',True):return
    from .economy_runtime import city_idle
    # Battle actors use global IDs, unlike account-local city pet IDs.
    # Battle snapshots send their own remapped avatar assignments.
    with session.router.team_arena.lock:
        if not city_idle(session):return
        packet=snapshot(session.database,session.account)
    # Initial assignment only; later city profiles carry their selected avatar.
    with presence.lock:
        if session in presence.messages:
            presence.messages[session].append(packet)
            session.avatar_sync_needed=False
