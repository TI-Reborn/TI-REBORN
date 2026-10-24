"""Session-bound contract windows. All mutations use the existing game service."""
from collections import deque
from contextlib import closing
import hashlib
import hmac
import json
import struct
import time

from tio.db_transaction import connect, transaction
from tio.protocol.pet_info import decode_pet_info


def snapshot(service, session):
    party = service.member(session)
    contract = service.contracts.active(party['id']) if party else None
    owner = session.account
    members = []
    if party:
        for member in party['members']:
            members.append(dict(name=service.name(member['owner']), ready=member['ready'],
                online=member['online'], selected=list(member['selected']),
                self=member['owner'] == owner, leader=member['owner'] == party['leader']))
    with closing(connect(service.path)) as db:
        pets = []
        for identity, human, raw in db.execute(
                'SELECT pet_id,human,pet_packet FROM owned_pets WHERE account=? ORDER BY pet_id', (owner,)):
            fields = decode_pet_info(bytes(raw), human_equipment=bool(human)).fields
            pets.append(dict(id=identity, name=fields['0x8c4489'].decode('cp1251'),
                level=fields['0x8c4aef'], hp=fields['0x8c4ab1'], available=fields['0x8c4ab1'] > 0 and fields['0x8c44a6'] != 4))
        result = db.execute('''SELECT i.template_json,i.outcome,i.finished_at,a.award_json,a.claimed
            FROM pve_contract_members m JOIN pve_contract_instances i ON i.id=m.instance_id
            LEFT JOIN pve_contract_awards a ON a.instance_id=i.id AND a.owner=m.owner
            WHERE m.owner=? AND i.state IN ('completed','failed')
            ORDER BY i.finished_at DESC LIMIT 1''', (owner,)).fetchone()
    invitations = [dict(id=i['id'], leader=service.name(i['leader']), expires_at=i['expires_at'])
                   for i in service.parties.invitations(owner)]
    templates = [dict(id=t['id'], name=t['name'], objective=t['objective'], levels=t['levels'], reward=t['reward'],
                      enemies=sum(t['enemies'].values()))
                 for t in service.contracts.catalog()]
    selected = next((m['selected'] for m in members if m['self']), [])
    busy = bool(service.hub.busy(session) or session.arena._fields or
                session.survival.searching(session.probe_character_id))
    frozen = bool(contract)
    leader = bool(party and party['leader'] == owner)
    city = bool(party and party['state'] == 'city')
    ready = bool(party and len(members) >= 2 and all(m['online'] and m['ready'] for m in members))
    data = dict(schema=1, name=service.name(owner), server_time=service.clock(),
        party=dict(id=party['id'], revision=party['revision'], state=party['state'], members=members) if party else None,
        invitations=invitations, pets=pets, selected=selected, catalog=templates,
        contract=dict(id=contract['id'], name=contract['template']['name'], state=contract['state'],
                      reward=contract['template']['reward'], target=contract['target']) if contract else None,
        result=dict(name=json.loads(result[0])['name'], outcome=result[1], finished_at=result[2],
                    reward=json.loads(result[3]) if result[3] else None, paid=bool(result[4])) if result else None,
        permissions=dict(create=not party and not busy, invite=leader and city and not frozen and not busy,
            edit=city and not frozen and not busy, take=leader and city and len(members) >= 2 and not frozen and not busy,
            ready=bool(party and party['state'] in ('city','at_target') and not busy),
            depart=leader and city and frozen and ready and not busy,
            start=leader and bool(party and party['state']=='at_target') and frozen and ready and not busy,
            cancel=leader and frozen and contract['state'] != 'active' and not busy))
    return data


def execute(service, session, request):
    """Strict typed API; no owner/account field is accepted from the client."""
    if not isinstance(request, dict) or set(request) - {'action','value','request_id'}:
        raise ValueError('Некорректный запрос окна контрактов')
    action = request.get('action')
    if action == 'state' and set(request) == {'action'}:
        return snapshot(service, session)
    request_id = request.get('request_id')
    if not isinstance(request_id, str) or len(request_id) != 32 or any(c not in '0123456789abcdef' for c in request_id):
        raise ValueError('Некорректный номер действия')
    fingerprint = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).digest()
    receipts = getattr(session, '_contracts_ui_receipts', None)
    if receipts is None:
        receipts = session._contracts_ui_receipts = {}
    if request_id in receipts:
        if not hmac.compare_digest(receipts[request_id], fingerprint):
            raise ValueError('Номер действия уже использован')
        return snapshot(service, session)
    value = request.get('value')
    commands = {
        'create': ('!party',['create']), 'leave': ('!party',['leave']),
        'disband': ('!party',['disband']), 'ready': ('!party',['ready']),
        'unready': ('!party',['unready']), 'cancel': ('!contracts',['cancel']),
        'start': ('!contracts',['start'])}
    if action in commands:
        if 'value' in request: raise ValueError('Лишнее значение действия')
        command, args = commands[action]
    elif action in ('invite','leader','kick','take'):
        if not isinstance(value,str) or not 1 <= len(value) <= 64 or any(c.isspace() or ord(c)<32 for c in value):
            raise ValueError('Укажите корректное имя или задание')
        command, args = ('!contracts' if action=='take' else '!party'), [action,value]
    elif action in ('accept','decline'):
        if type(value) is not int or not 1<=value<=2**63-1: raise ValueError('Некорректное приглашение')
        command, args = '!party', [action,str(value)]
    elif action == 'select':
        if not isinstance(value,list) or not 1<=len(value)<=2 or any(type(i) is not int or not 1<=i<=2**31-1 for i in value):
            raise ValueError('Выберите одного или двух бойцов')
        command, args = '!party', ['select', *map(str,value)]
    elif action != 'depart':
        raise ValueError('Неизвестное действие')
    before = {owner:deque(queue) for owner,queue in service.hub.queues.items()}
    try:
        with transaction(service.path):
            if action == 'depart':
                if 'value' in request: raise ValueError('Лишнее значение действия')
                state = snapshot(service, session)
                if not state['permissions']['depart']: raise ValueError('Все участники должны быть готовы к выходу')
                target = state['contract']['target']
                packets = service.travel_map(session, struct.pack('<Bii',0x1b,target['x'],target['y']))
                for packet in packets: service.hub.put(service.hub.identity(session),packet)
            else:
                service._command(session, command, args)
    except BaseException:
        service.hub.queues = before
        raise
    # Session-local retry receipts disappear with the authentication session.
    # Contract completion and payouts retain their existing durable receipts.
    if len(receipts)>=128: receipts.pop(next(iter(receipts)))
    receipts[request_id] = fingerprint
    return snapshot(service, session)


def handle(router, token, request):
    service = router.contracts
    if service is None: return dict(ok=False,error='Контракты недоступны')
    with service.hub.lock:
        sessions = [s for s in service.hub.players.values()
                    if getattr(s,'contracts_ui_token',None) is not None
                    and hmac.compare_digest(s.contracts_ui_token,token)
                    and getattr(s,'authenticated_account',None) and not s.stopping.is_set()
                    and service.hub.identity(s) not in service.hub.offline]
        if len(sessions)!=1: return dict(ok=False,error='Войдите персонажем в игру',code='not_authenticated')
        session=sessions[0]
        now=time.monotonic()
        if now-getattr(session,'_contracts_ui_last',0)<.15:
            return dict(ok=False,error='Подождите перед следующим действием',code='rate_limited')
        session._contracts_ui_last=now
        try: return dict(ok=True,state=execute(service,session,request))
        except (ValueError,UnicodeError) as error: return dict(ok=False,error=str(error))
