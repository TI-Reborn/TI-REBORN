"""Native TrueSkill queue, one to four selected fighters per real account.

Initial hosted format: 1v1, levels 4..20 within the same classic band.
No AI seats, wagers, client-reported results or writes to saved selections.
"""
from contextlib import closing
from dataclasses import replace
from types import SimpleNamespace
import struct
from tio.db_transaction import connect
from tio.matchmaking import SearchTicket
from tio.protocol.system_message import encode_shop_error
from tio.protocol.pet_info import decode_pet_info
from tio.protocol.ranked import decode_join,encode_info,encode_flags,encode_scores,encode_roster,encode_accepted
from tio import ranked

RANKED_TOWNS=(2,5)


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
                self.put(owner,*gears,self.ranked_info(owner));return True
            if packet==b'\xc6\x23':
                if owner in self.battles:raise ValueError('Сначала завершите бой')
                self.ranked_waiting.pop(owner,None);self.put(owner,b'\xc6\x06');return True
            if packet[:2]!=b'\xc6\x21':
                raise ValueError('Отмените поиск рейтингового боя')
            if owner in self.battles or owner in self.results or owner in self.survival_waiting or self.lobbies.room(owner):
                raise ValueError('Сначала завершите бой или отмените поиск')
            if any(s.probe_character_id in r.members for r in s.arena.rooms.snapshot()):
                raise ValueError('Сначала выйдите из текущего боя')
            if not s.locations or s.locations.current(s.account) not in RANKED_TOWNS:
                raise ValueError('Рейтинговая битва доступна в Denver и New York')
            flags,pets=decode_join(packet)
            from tio.owned_pets import OwnedPetStore
            from tio.battle_modes import level_band
            owned={r[0]:r for r in OwnedPetStore(s.database).list(s.account)}
            actors=[];levels=[]
            for identity,equipment,bonus in pets:
                if bonus or equipment:raise ValueError('Рейтинговый бой пока использует сохранённую экипировку без дополнительных бонусов')
                row=owned.get(identity)
                if row is None:raise ValueError('Боец не принадлежит вашему аккаунту')
                resource=int.from_bytes(row[1][5:9],'little');human=resource in (1,2,6)
                pet=decode_pet_info(row[1],human_equipment=human).fields
                level=pet['0x8c4aef']
                if not 4<=level<=20:raise ValueError('Рейтинговый бой: уровни 4–20')
                if pet['0x8c4ab1']!=pet['0x8c4a07']:raise ValueError('Перед рейтинговым боем полностью вылечите бойца')
                actors.append(identity);levels.append(level)
            if len({level_band(level) for level in levels})!=1:
                raise ValueError('Рейтинговые бойцы должны быть одного диапазона уровней')
            ticket=SearchTicket(owner,tuple(actors),tuple(levels),self.clock())
            prior=self.ranked_waiting.get(owner)
            if prior and (prior.actors,prior.levels)!=(ticket.actors,ticket.levels):raise ValueError('Сначала отмените прежний поиск')
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
        candidates=[t for o,t in self.ranked_waiting.items() if o!=owner and level_band(t.levels[0])==level_band(first.levels[0])
                    and len(t.actors)==len(first.actors)
                    and self.players[o].account!=self.players[owner].account and self.players[o].database==self.players[owner].database]
        candidates=[t for t in candidates if authenticated(t.character_id)!=authenticated(owner)]
        if not candidates:return
        # Prefer the closest current rating, then queue age.
        score=lambda t:ranked.skill(*ranked.snapshot(self.players[t.character_id].database,self.players[t.character_id].account))
        other=min(candidates,key=lambda t:(abs(score(t)-score(first)),t.joined_at,t.character_id))
        tickets=sorted((first,other),key=lambda t:(t.joined_at,t.character_id))
        seats=[];teams=[]
        for side,t in enumerate(tickets):
            s=self.players[t.character_id]
            if s.locations.current(s.account) not in RANKED_TOWNS:raise ValueError('Игрок покинул рейтинговый город')
            seats.append((t.character_id,side,s.database,s.account,t,False));teams.append([t.character_id])
        proposal=SimpleNamespace(mode=21,soldiers=len(first.actors),band=level_band(tickets[0].levels[0]),captain=tickets[0].character_id)
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
        return dict(winner=None if battle['ranked_winner']==2 else battle['ranked_winner'],teams=battle['ranked_teams'])
