"""Shared TrueSkill friend party; a party is one indivisible matchmaking side."""
from dataclasses import dataclass,field
from types import SimpleNamespace
from contextlib import closing
from tio.db_transaction import connect
from tio.character_identity import auth_account,owner_for_name
from tio.rating_visibility import QA_LOGIN
from tio.protocol.ranked_party import decode,invite,snapshot
from tio.protocol.system_message import encode_shop_error
from tio.protocol.chat import encode_system_message

@dataclass
class Party:
    leader:int
    members:list
    slots:dict=field(default_factory=dict)
    tickets:dict=field(default_factory=dict)

def state(hub):
    if not hasattr(hub,'ranked_parties'):hub.ranked_parties={};hub.ranked_invitations={}
    return hub.ranked_parties,hub.ranked_invitations

def party(hub,owner):return getattr(hub,'ranked_parties',{}).get(owner)

def wire(hub,group,owner,viewer):return hub.players[viewer].probe_character_id if owner==viewer else 0x4000+group.members.index(owner)

def eligible(hub,owner,*,group=False):
    from .ranked_arena import RANKED_TOWNS
    s=hub.players.get(owner)
    if s is None or owner in hub.offline:raise ValueError('Игрок не в сети')
    if owner in hub.battles or owner in hub.results or owner in hub.survival_waiting or hub.lobbies.room(owner) or hub.wager_busy(owner) or hub.assault_group(s) or hub.mine_waiting(owner):raise ValueError('Игрок занят другим боем или группой')
    if getattr(s.arena,'_fields',{}) or any(s.probe_character_id in room.members for room in s.arena.rooms.snapshot()):raise ValueError('Сначала завершите текущий бой')
    if not group and owner in hub.ranked_waiting:raise ValueError('Сначала отмените поиск TrueSkill')
    if not s.locations or s.locations.current(s.account) not in RANKED_TOWNS:raise ValueError('Группа TrueSkill доступна в городах с вносом вещей')
    hub.city(owner)  # includes prison and location admission fences
    if not any(4<=f['0x8c4aef']<=20 for _,f in roster(hub,owner)):raise ValueError('Для TrueSkill нужен боец уровня 4–20')
    return s

def roster(hub,owner):
    from tio.owned_pets import OwnedPetStore
    from tio.protocol.pet_info import decode_pet_info
    return [(identity,decode_pet_info(raw,human_equipment=int.from_bytes(raw[5:9],'little') in (1,2,6)).fields) for identity,raw,_ in OwnedPetStore(hub.players[owner].database).list(hub.players[owner].account)]

def notify(hub,group):
    for viewer in group.members:
        rows=[]
        for owner in group.members:
            s=hub.players[owner];chosen=group.tickets.get(owner);owned=roster(hub,owner)
            pets=[f for identity,f in owned if chosen and identity in chosen.actors]
            # Unready members have no committed loadout; retain allocated slots.
            shown=[(f['0x8c446f'],0,f['0x8c4aef'],f['0x8c4ab1'],f['0x8c4a07'],0,0) for f in pets]
            rows.append((wire(hub,group,owner,viewer),s.probe_character_name,max((f['0x8c4aef'] for _,f in owned),default=1),0,0,2 if chosen else 0,group.slots[owner],shown))
        from tio.ranked_tokens import status
        s=hub.players[viewer]
        with closing(connect(s.database)) as db,db:_,tokens=status(db,s.account)
        hub.put(viewer,snapshot(wire(hub,group,group.leader,viewer),rows,min(tokens,65535)))

def cancel(hub,group):
    for owner in group.members:
        if hub.ranked_waiting.pop(owner,None) is not None:hub.put(owner,b'\xc6\x06')
    group.tickets.clear()

def leave(hub,owner):
    groups,invitations=state(hub);group=groups.get(owner)
    for target,sender in tuple(invitations.items()):
        if target==owner:invitations.pop(target,None)
        elif sender==owner:invitations[target]=0  # consume the late bool answer safely
    if group is None:return
    cancel(hub,group);group.members.remove(owner);groups.pop(owner,None);group.slots.pop(owner,None)
    hub.put(owner,snapshot(0,()))
    if not group.members:return
    if group.leader==owner:group.leader=group.members[0]
    notify(hub,group)

def handle(hub,owner,packet):
    if packet[:2] not in (b'\xc6\x32',b'\xc6\x33',b'\xc6\x34',b'\xc6\x37',b'\xc6\x38'):return False
    try:
        groups,invitations=state(hub);op,value=decode(packet);group=groups.get(owner)
        if op==0x33:
            if owner in hub.battles or owner in hub.results:raise ValueError('Сначала завершите бой')
            leave(hub,owner);return True
        eligible(hub,owner,group=group is not None)
        if op==0x32:
            if group and group.leader!=owner:raise ValueError('Приглашать может только лидер группы')
            if group and any(o in hub.ranked_waiting for o in group.members):raise ValueError('Сначала отмените поиск группы')
            name,message=value;s=hub.players[owner]
            with closing(connect(s.database)) as db:account=owner_for_name(db,name)
            target=next((o for o,p in hub.players.items() if p.database==s.database and p.account==account and o not in hub.offline),None)
            if target is None:raise ValueError('Игрок не в сети')
            other=eligible(hub,target)
            roots=[auth_account(s.database,p.account) for p in (s,other)]
            if roots[0]==roots[1]:raise ValueError('Нельзя пригласить персонажа своего аккаунта')
            if bool(QA_LOGIN.fullmatch(roots[0]))!=bool(QA_LOGIN.fullmatch(roots[1])):raise ValueError('Игрок недоступен для приглашения')
            if target in groups:raise ValueError('Игрок уже состоит в группе TrueSkill')
            if target in invitations:
                if invitations[target]==owner:return True
                raise ValueError('Игрок уже отвечает на приглашение')
            if group and (len(group.members)>=4 or sum(group.slots.values())>=4):raise ValueError('В группе нет свободного места')
            now=hub.clock()
            if now<getattr(s,'ranked_invite_after',0):raise ValueError('Подождите перед следующим приглашением')
            if group is None:group=Party(owner,[owner],{owner:1});groups[owner]=group
            invitations[target]=owner;s.ranked_invite_after=now+2
            notify(hub,group);hub.put(target,invite(s.probe_character_name,message))
            hub.put(owner,encode_system_message(1,b'Server','Приглашение в группу TrueSkill отправлено'))
        elif op==0x37:
            sender=invitations.pop(owner,None);group=groups.get(sender)
            if sender is None or group is None or group.leader!=sender:raise ValueError('Приглашение уже закрыто')
            if not value:hub.put(sender,encode_system_message(1,b'Server','Приглашение в группу TrueSkill отклонено'));return True
            eligible(hub,sender,group=True)
            if owner in groups:raise ValueError('Вы уже состоите в группе TrueSkill')
            if len(group.members)>=4 or sum(group.slots.values())>=4:raise ValueError('В группе нет свободного места')
            cancel(hub,group);group.members.append(owner);group.slots[owner]=1;groups[owner]=group;notify(hub,group)
        elif op==0x34:
            if group is None:raise ValueError('Сначала создайте группу TrueSkill')
            target,slots=value;target=next((o for o in group.members if wire(hub,group,o,owner)==target),None)
            if target is None or owner not in (group.leader,target):raise ValueError('Нельзя изменять чужие места в группе')
            if slots==0:leave(hub,target);return True
            if sum(group.slots.values())-group.slots[target]+slots>4:raise ValueError('В группе не может быть больше четырёх бойцов')
            cancel(hub,group);group.slots[target]=slots;notify(hub,group)
        elif op==0x38:
            if group is None:hub.put(owner,snapshot(0,()))
            else:notify(hub,group)
    except ValueError as error:hub.put(owner,encode_shop_error(str(error)))
    return True

def submit(hub,owner,ticket):
    group=party(hub,owner)
    if group is None:return False
    if any(o in hub.ranked_waiting for o in group.members):raise ValueError('Сначала отмените поиск группы')
    if len(ticket.actors)!=group.slots[owner]:raise ValueError('Выберите столько бойцов, сколько мест выделено вам в группе')
    all_ready=all(o in group.tickets for o in group.members)
    group.tickets[owner]=ticket
    if all_ready:
        if owner!=group.leader:raise ValueError('Начать общий поиск может лидер группы')
        from tio.battle_modes import level_band
        if len({level_band(l) for t in group.tickets.values() for l in t.levels})!=1:raise ValueError('Бойцы группы должны быть одного уровневого диапазона')
        miners=sum(f['0x8c446f']==6 for o,t in group.tickets.items() for identity,f in roster(hub,o) if identity in t.actors)
        if miners>1:raise ValueError('В группу TrueSkill можно взять только одного шахтёра')
        for o in group.members:eligible(hub,o,group=True)
        hub.ranked_waiting.update(group.tickets)
        for o in group.members:hub.put(o,b'\xc6\x05')
        hub.match_ranked(owner)
    else:notify(hub,group)
    return True

def units(hub,candidates):
    by_id={t.character_id:t for t in candidates};used=set();result=[]
    for ticket in candidates:
        owner=ticket.character_id
        if owner in used:continue
        group=party(hub,owner)
        if group is None:result.append(ticket);continue
        used.update(group.members)
        if not all(o in by_id for o in group.members):continue
        members=tuple(by_id[o] for o in group.members)
        result.append(SimpleNamespace(character_id=group.leader,actors=tuple(range(sum(len(t.actors) for t in members))),levels=tuple(l for t in members for l in t.levels),joined_at=min(t.joined_at for t in members),members=members))
    return result

def consumed(hub,tickets):
    groups,invitations=state(hub)
    for ticket in tickets:
        owner=ticket.character_id;hub.ranked_waiting.pop(owner,None)
        if groups.pop(owner,None) is not None:hub.put(owner,snapshot(0,()))
        for target,sender in tuple(invitations.items()):
            if target==owner:invitations.pop(target,None)
            elif sender==owner:invitations[target]=0
