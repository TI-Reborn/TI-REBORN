"""Native TrueSkill: authoritative real-account squads, levels4..20.

Complete four-fighter teams take priority; balanced smaller duels retain
the existing low-population policy. Selections never rewrite barracks slots.
"""
from contextlib import closing
from dataclasses import dataclass,replace
from types import SimpleNamespace
import struct
from tio.db_transaction import connect
from tio.matchmaking import SearchTicket
from tio.protocol.system_message import encode_shop_error
from tio.protocol.pet_info import decode_pet_info
from tio.protocol.ranked import decode_join,encode_info,encode_flags,encode_scores,encode_roster,encode_accepted
from tio import ranked

RANKED_TOWNS=(2,5,8,18)


@dataclass(frozen=True)
class RankedTicket(SearchTicket):
    selections: tuple = ()
    flags: tuple = (0,0)


class RankedArena:
    def ranked_info(self,owner):
        s=self.players[owner]
        with closing(connect(s.database)) as db:return encode_info(*ranked.profile(db,s.account))

    def handle_ranked(self,owner,packet):
        s=self.players[owner]
        try:
            if packet in (b'\xc6\x02',b'\xc6\x20'):
                from tio.arena_gears import catalogue_packet
                # C6/18 touches the city button in the original client. Keep
                # rating queries during combat free of city UI updates.
                gears=() if owner in self.battles or owner in self.results else (catalogue_packet(),)
                from tio.ranked_tokens import packets
                with closing(connect(s.database)) as db,db:tokens=packets(db,s.account)
                self.put(owner,*gears,self.ranked_info(owner),*tokens);return True
            if packet==b'\xc6\x23':
                if owner in self.battles:raise ValueError('Сначала завершите бой')
                self.ranked_waiting.pop(owner,None);self.put(owner,b'\xc6\x06');return True
            if packet[:2]!=b'\xc6\x21':
                raise ValueError('Отмените поиск рейтингового боя')
            if any('points' in b and not b['finished'] and s.account in b.get('ranked_forfeits',set()) for b in self.battles.values()):
                raise ValueError('Дождитесь окончания предыдущего рейтингового боя')
            if owner in self.battles or owner in self.results or owner in self.survival_waiting or self.lobbies.room(owner):
                raise ValueError('Сначала завершите бой или отмените поиск')
            if any(s.probe_character_id in r.members for r in s.arena.rooms.snapshot()):
                raise ValueError('Сначала выйдите из текущего боя')
            if not s.locations or s.locations.current(s.account) not in RANKED_TOWNS:
                raise ValueError('Рейтинговая битва доступна в городах с вносом вещей')
            flags,pets=decode_join(packet)
            if flags[0]:
                from tio.ranked_tokens import status
                with closing(connect(s.database)) as db,db:_,balance=status(db,s.account)
                if not balance:raise ValueError('Нет жетонов для бонусного набора TrueSkill')
            from tio.owned_pets import OwnedPetStore
            from tio.battle_modes import level_band
            owned={r[0]:r for r in OwnedPetStore(s.database).list(s.account)}
            actors=[];levels=[]
            miners=0
            for identity,equipment,bonus in pets:
                row=owned.get(identity)
                if row is None:raise ValueError('Боец не принадлежит вашему аккаунту')
                resource=int.from_bytes(row[1][5:9],'little');human=resource in (1,2,6)
                pet=decode_pet_info(row[1],human_equipment=human).fields
                miners+=int(resource==6)
                if miners>1:raise ValueError('В бой TrueSkill можно взять только одного шахтёра')
                from tio.ranked_loadout import validate
                validate(row[1],row[2],human,equipment)
                level=pet['0x8c4aef']
                if not 4<=level<=20:raise ValueError('Рейтинговый бой: уровни 4–20')
                if pet['0x8c4ab1']!=pet['0x8c4a07']:raise ValueError('Перед рейтинговым боем полностью вылечите бойца')
                actors.append(identity);levels.append(level)
            ticket=RankedTicket(owner,tuple(actors),tuple(levels),self.clock(),selections=pets,flags=flags)
            prior=self.ranked_waiting.get(owner)
            if prior and (prior.actors,prior.levels,prior.selections,prior.flags)!=(ticket.actors,ticket.levels,ticket.selections,ticket.flags):raise ValueError('Сначала отмените прежний поиск')
            self.ranked_waiting.setdefault(owner,ticket)
            self.put(owner,self.ranked_info(owner))
            self.match_ranked(owner)
        except ValueError as error:
            self.ranked_waiting.pop(owner,None)
            self.put(owner,encode_shop_error(str(error)[:180]),b'\xc6\x06')
        return True

    def match_ranked(self,owner):
        from tio.battle_modes import level_band
        first=self.ranked_waiting[owner]
        from tio.character_identity import auth_account
        authenticated=lambda o:auth_account(self.players[o].database,self.players[o].account)
        candidates=[];roots=set()
        for t in sorted(self.ranked_waiting.values(),key=lambda t:(t.joined_at,t.character_id)):
            if self.players[t.character_id].database!=self.players[owner].database:continue
            root=authenticated(t.character_id)
            if root in roots:continue
            roots.add(root);candidates.append(t)
            if len(candidates)==32:break
        # Prefer the closest current rating, then queue age.
        score=lambda t:ranked.skill(*ranked.snapshot(self.players[t.character_id].database,self.players[t.character_id].account))
        # Bounded subset DP: complete 4+4 groups may contain different numbers
        # of real accounts (4 vs 2+2, 3+1 vs 1+1+2, etc.). Never split a squad.
        states={(0,0):((),())}
        for t in candidates:
            for (a,b),groups in tuple(states.items()):
                for side,total in enumerate((a,b)):
                    if total+len(t.actors)>4:continue
                    key=(a+len(t.actors),b) if side==0 else (a,b+len(t.actors))
                    new=(groups[0]+(t,),groups[1]) if side==0 else (groups[0],groups[1]+(t,))
                    states.setdefault(key,new)
        groups=states.get((4,4))
        if groups is None:
            # Explicit low-population policy: retain balanced smaller duels.
            peers=[t for t in candidates if t.character_id!=owner and authenticated(t.character_id)!=authenticated(owner) and len(t.actors)==len(first.actors)]
            if not peers:return
            other=min(peers,key=lambda t:(abs(score(t)-score(first)),t.joined_at,t.character_id))
            pair=sorted((first,other),key=lambda t:(t.joined_at,t.character_id));groups=((pair[0],),(pair[1],))
        tickets=tuple(t for group in groups for t in group)
        seats=[];teams=[]
        for side,group in enumerate(groups):
            teams.append([])
            for t in group:
                s=self.players[t.character_id]
                if s.locations.current(s.account) not in RANKED_TOWNS:raise ValueError('Игрок покинул рейтинговый город')
                seats.append((t.character_id,side,s.database,s.account,t,False));teams[-1].append(t.character_id)
        proposal=SimpleNamespace(mode=21,soldiers=sum(len(t.actors) for t in groups[0]),band=min(level_band(l) for t in tickets for l in t.levels),captain=tickets[0].character_id)
        self.start_match(proposal,seats,teams,set(),lambda:[self.ranked_waiting.pop(t.character_id,None) for t in tickets])

    def ranked_packets(self,battle,owner,*,scene=False):
        points=battle.get('points')
        if points is None:return ()
        field=battle['field'];names=battle['names']
        packets=(encode_roster(field,names,points.limit,viewer=owner,character_id=self.players[owner].probe_character_id),) if scene else ()
        return (*packets,*encode_flags(points),encode_scores(points),self.ranked_info(owner))

    def ranked_refresh(self,battle):
        for owner in battle['humans']:self.put(owner,*self.ranked_packets(battle,owner))

    def ranked_report(self,battle):
        if 'ranked_winner' not in battle:return None
        result=dict(winner=None if battle['ranked_winner']==2 else battle['ranked_winner'],teams=battle['ranked_teams'])
        if battle.get('ranked_forfeits'):result['forfeits']=sorted(battle['ranked_forfeits'])
        return result
