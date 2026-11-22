"""Native city services and delayed dismissal worker under the shared hub lock."""
import time,uuid
from .city_services import CityServices
from .city_operations import CityError,public_name
from .economy_runtime import busy_accounts,refresh_inventory
from tio.db_transaction import transaction
from tio.services_completion import ServiceRejected
from tio.wallets import WalletStore
from tio.protocol.asset_count import encode_asset_count
from tio.protocol.chat import encode_system_message
from tio.protocol.hire import decode_paid_rename
from .service_operations import prepare_service,execute_service

def service(router):
    value=getattr(router,'_city_services',None)
    if value is None:
        with router.team_arena.lock:
            value=getattr(router,'_city_services',None)
            if value is None:
                value=CityServices(router);router._city_services=value
    return value

def available(manager,db,owner):
    manager.operations._running()
    return manager.operations._available(db,owner,busy_accounts(manager.router,db))[0]

def native(session,*,command=None,pet_id=None,rename_packet: bytes | None = None) -> tuple[bytes, ...]:
    renaming = command is not None or rename_packet is not None
    if rename_packet is not None:
        pet_id, new_name = decode_paid_rename(rename_packet)
    manager=service(session.router)
    with session.router.team_arena.lock:
        with transaction(session.database) as db:
            allowed=available(manager,db,session.account)
            identity='native-'+uuid.uuid4().hex
            if command is not None:
                operation=prepare_service('service_rename_command',identity,dict(command=command))
            elif rename_packet is not None:
                operation=prepare_service('service_rename',identity,dict(petId=pet_id,newName=new_name))
            else:
                operation=prepare_service('service_dismiss',identity,dict(petId=pet_id))
            execute_service(operation,db=db,path=manager.path,helper=manager.helper,owner=session.account,allowed=allowed)
            name=public_name(db,session.account) if renaming else None
        if name:session.probe_character_name=name.encode('cp1251')
        manager.invalidate(session.account)
        replies=refresh_inventory(session,force=True)+(encode_asset_count(WalletStore(session.database).ensure(session.account)),)
        if not renaming:replies+=(encode_system_message(4,b'Services','Увольнение назначено через 48 часов. Точная дата доступна в разделе услуг на сайте.'),)
        return replies

def tick(router):
    manager=service(router);now=time.monotonic()
    if now<getattr(manager,'next_dismiss_tick',0):return
    manager.next_dismiss_tick=now+1
    hub=router.team_arena
    for owner in manager.helper.due_owners(limit=50):
        with hub.lock:
            try:
                with transaction(manager.path) as db:
                    if not available(manager,db,owner):continue
                    result=manager.helper.finalize_due(owner,allowed=True)
                if result['completed']:
                    with router.lock:sessions=tuple(router.active_accounts.values())
                    for session in sessions:
                        if getattr(session,'account',None)==owner:
                            session._economy_inventory_digest=None
                            actor=hub.identities.get(session)
                            if actor is not None:hub.put(actor,*result['packets'])
            except (ValueError,CityError):continue
