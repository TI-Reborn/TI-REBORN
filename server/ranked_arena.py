"""Native TrueSkill: authoritative real-account squads, levels4..20.

Equal fighter counts for solo squads and premade groups.
"""
from contextlib import closing
import logging
from dataclasses import dataclass,replace
from types import SimpleNamespace
import struct
from tio.db_transaction import connect
from tio.matchmaking import SearchTicket, SquadAdmissionError
from tio.ranked_party import (MAX_FIGHTERS, HUMAN_RESOURCES, MINER_RESOURCE, PartyUnit,
    RankedRejection, is_ranked_level, validate_miner_count)
from tio.protocol.binary import PacketError
from tio.protocol.system_message import encode_shop_error
from tio.protocol.pet_info import decode_pet_info
from tio.protocol.ranked import SEARCH_CANCELLED_PACKET, decode_join,encode_info,encode_flags,encode_scores,encode_roster,encode_accepted
from tio import ranked

RANKED_TOWNS=(2,5,8,18)
LOG=logging.getLogger('tio.server')


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
                from .ranked_party import party,cancel,notify
                group=party(self,owner)
                if group is not None and owner not in self.battles and owner not in self.results:
                    if any(o in self.ranked_waiting for o in group.members):
                        cancel(self,group);notify(self,group)
                    elif owner in group.tickets:
                        group.tickets.pop(owner,None);notify(self,group)
                    return True
                # A close can race the final matchmaking step. Never turn a
                # late search cancellation into a forfeit or clear combat UI.
                if owner in self.battles or owner in self.results:return True
                # Opening the original selector also sends this request. An
                # idle C6/06 would erase its just-selected fighters (9537a8).
                if self.ranked_waiting.pop(owner,None) is not None:
                    self.put(owner,SEARCH_CANCELLED_PACKET)
                return True
            if packet[:2]!=b'\xc6\x21':
                raise RankedRejection('Отмените поиск рейтингового боя')
            if any('points' in b and not b['finished'] and s.account in b.get('ranked_forfeits',set()) for b in self.battles.values()):
                raise RankedRejection('Дождитесь окончания предыдущего рейтингового боя')
            if owner in self.battles or owner in self.results or owner in self.survival_waiting or self.lobbies.room(owner):
                raise RankedRejection('Сначала завершите бой или отмените поиск')
            if any(s.probe_character_id in r.members for r in s.arena.rooms.snapshot()):
                raise RankedRejection('Сначала выйдите из текущего боя')
            if not s.locations or s.locations.current(s.account) not in RANKED_TOWNS:
                raise RankedRejection('Рейтинговая битва доступна в городах с вносом вещей')
            flags,pets=decode_join(packet)
            if flags[0]:
                from tio.ranked_tokens import status
                with closing(connect(s.database)) as db,db:_,balance=status(db,s.account)
                if not balance:raise RankedRejection('Нет жетонов для бонусного набора TrueSkill')
            from tio.owned_pets import OwnedPetStore
            from tio.battle_modes import level_band
            owned={r[0]:r for r in OwnedPetStore(s.database).list(s.account)}
            actors=[];levels=[]
            miners=0
            for identity,equipment,bonus in pets:
                row=owned.get(identity)
                if row is None:raise RankedRejection('Боец не принадлежит вашему аккаунту')
                resource=int.from_bytes(row[1][5:9],'little');human=resource in HUMAN_RESOURCES
                pet=decode_pet_info(row[1],human_equipment=human).fields
                miners+=int(resource==MINER_RESOURCE)
                validate_miner_count(miners)
                from tio.ranked_loadout import validate
                validate(row[1],row[2],human,equipment)
                level=pet['0x8c4aef']
                if not is_ranked_level(level):raise RankedRejection('Рейтинговый бой: уровни 4–20')
                if pet['0x8c4ab1']!=pet['0x8c4a07']:raise RankedRejection('Перед рейтинговым боем полностью вылечите бойца')
                actors.append(identity);levels.append(level)
            ticket=RankedTicket(owner,tuple(actors),tuple(levels),self.clock(),selections=pets,flags=flags)
            from .ranked_party import submit
            if submit(self,owner,ticket):return True
            prior=self.ranked_waiting.get(owner)
            if prior is None:
                self.ranked_waiting[owner]=ticket
            elif (prior.actors,prior.levels,prior.selections,prior.flags)!=(ticket.actors,ticket.levels,ticket.selections,ticket.flags):
                # The native selector stays open while searching, so a repeated
                # Continue edits the search. The latest valid choice wins and the
                # queue age is kept; rejecting it used to drop the player silently.
                self.ranked_waiting[owner]=replace(ticket,joined_at=prior.joined_at)
                LOG.info('ranked_search_updated owner=%s fighters=%d',owner,len(ticket.actors))
            self.put(owner,self.ranked_info(owner))
            self.match_ranked(owner)
        except (PacketError, RankedRejection, SquadAdmissionError) as error:
            from .ranked_party import party,cancel,notify
            group=party(self,owner)
            if group is not None:cancel(self,group);notify(self,group)
            else:self.ranked_waiting.pop(owner,None)
            self.put(owner,encode_shop_error(str(error)[:180]),SEARCH_CANCELLED_PACKET)
        return True

    def match_ranked(self,owner):
        from tio.character_identity import auth_account
        from .ranked_party import party,units
        authenticated=lambda o:auth_account(self.players[o].database,self.players[o].account)
        from tio.rating_visibility import QA_LOGIN
        qa_pool=bool(QA_LOGIN.fullmatch(authenticated(owner)))
        group=party(self,owner)
        size=(len(self.ranked_waiting[owner].actors) if group is None else
              sum(len(self.ranked_waiting[member].actors) for member in group.members))
        candidates=[];roots=set();skipped={'database':0,'qa_pool':0,'same_login':0}
        for t in sorted(self.ranked_waiting.values(),key=lambda t:(t.joined_at,t.character_id)):
            if self.players[t.character_id].database!=self.players[owner].database:skipped['database']+=1;continue
            candidate_group=party(self,t.character_id)
            if (group is None)!=(candidate_group is None):continue
            if candidate_group is None:
                if len(t.actors)!=size:continue
            elif sum(candidate_group.slots.values())!=size:continue
            root=authenticated(t.character_id)
            # Reserved disposable QA logins never face ordinary players.
            # Character aliases cannot cross the authenticated root's pool.
            if bool(QA_LOGIN.fullmatch(root))!=qa_pool:skipped['qa_pool']+=1;continue
            if root in roots:skipped['same_login']+=1;continue
            roots.add(root);candidates.append(t)
            if len(candidates)==32:break
        candidates=units(self,candidates)
        entrant=next((t for t in candidates if t.character_id==owner),None)
        opponent=next((t for t in candidates if t.character_id!=owner and len(t.actors)==size),None)
        if entrant is None or opponent is None:
            LOG.info('ranked_search_waiting owner=%s queued=%d candidates=%d skipped=%s',
                     owner,len(self.ranked_waiting),len(candidates),
                     ','.join(f'{k}:{v}' for k,v in skipped.items()))
            return
        pair=sorted((entrant,opponent),key=lambda t:(t.joined_at,t.character_id))
        groups=tuple(unit.members if isinstance(unit,PartyUnit) else (unit,) for unit in pair)
        from tio.battle_modes import level_band
        tickets=tuple(t for group in groups for t in group)
        seats=[];teams=[]
        for side,group in enumerate(groups):
            teams.append([])
            for t in group:
                s=self.players[t.character_id]
                if s.locations.current(s.account) not in RANKED_TOWNS:raise RankedRejection('Игрок покинул рейтинговый город')
                seats.append((t.character_id,side,s.database,s.account,t,False));teams[-1].append(t.character_id)
        proposal=SimpleNamespace(mode=21,soldiers=size,band=min(level_band(l) for t in tickets for l in t.levels),captain=tickets[0].character_id)
        from .ranked_party import consumed
        self.start_match(proposal,seats,teams,set(),lambda:consumed(self,tickets))

    def ranked_packets(self,battle,owner,*,scene=False):
        points=battle.get('points')
        if points is None:return ()
        field=battle['field'];names=battle['names']
        bots = battle['bots'] if battle.get('kind') == 'tournament' else ()
        packets=(encode_roster(field,names,points.limit,viewer=owner,character_id=self.players[owner].probe_character_id,bots=bots),) if scene else ()
        return (*packets,*encode_flags(points),encode_scores(points))

    def ranked_refresh(self,battle):
        for owner in battle['humans']:self.put(owner,*self.ranked_packets(battle,owner))

    def ranked_flag_count(self,battle,owner: int) -> bytes:
        from tio.protocol.chat import encode_system_message
        points=battle['points']
        side=battle['field'].teams[owner]
        ours=points.owners.count(side);theirs=points.owners.count(1-side)
        return encode_system_message(3,b'TIO',f'Флаги — ваша команда {ours}, противник {theirs}')

    def ranked_capture_refresh(self,battle,previous: tuple) -> None:
        self.ranked_refresh(battle)
        if tuple(battle['points'].owners)!=previous:
            for owner in battle['humans']:self.put(owner,self.ranked_flag_count(battle,owner))

    def ranked_report(self,battle):
        if battle.get('bots') or 'ranked_teams' not in battle or 'ranked_winner' not in battle:return None
        result=dict(winner=None if battle['ranked_winner']==2 else battle['ranked_winner'],teams=battle['ranked_teams'])
        if battle.get('ranked_forfeits'):result['forfeits']=sorted(battle['ranked_forfeits'])
        return result
