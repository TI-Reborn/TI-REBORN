"""Authenticated B2/06 tactical marks, delivered to allies through B2/07.

One native mark per author; the native HUD expires it after 200 seconds.
Wall-clock expiry and rate samples are primitive battle state so existing
checkpoints preserve them without new snapshot classes or clock rebasing.
"""
import time

from tio.protocol.tactical_marks import (TacticalMark, PLACE, REMOVE,
    NATIVE_TTL_SECONDS, decode_tactical_mark, encode_tactical_mark_notification)

MARK_RATE_LIMIT=5
MARK_RATE_WINDOW_SECONDS=5


class TacticalMarks:
    def tactical_wall(self):
        journal=getattr(self,'journal',None)
        return journal.wall() if journal is not None else time.time()

    def _mark_member(self,battle,owner):
        return (owner in battle['humans'] and self.battles.get(owner) is battle
                and owner in self.players)

    def _mark_recipients(self,battle,author):
        return tuple(target for target in sorted(battle['humans'])
            if self._mark_member(battle,target) and target not in self.offline
            and battle['field'].allied(author,target))

    def _send_tactical_mark(self,battle,author,kind,x,y):
        for target in self._mark_recipients(battle,author):
            # Match exactly the per-viewer identities in BattleMemberList25.
            character=self.players[target].probe_character_id if author==target else author
            self.put(target,encode_tactical_mark_notification(TacticalMark(kind,character,x,y)))

    def handle_tactical_mark(self,owner,packet):
        if packet[:2]!=b'\xb2\x06':return False
        request=decode_tactical_mark(packet)
        battle=self.battles.get(owner)
        if (battle is None or battle['finished'] or battle.get('faulted')
                or not self._mark_member(battle,owner) or owner in self.offline
                or owner in self.returning):
            raise ValueError('Тактические отметки доступны только в загруженном бою')
        character=self.players[owner].probe_character_id
        # The physical place caller sends the local character ID. The physical
        # remove caller sends zero; authenticate its author from the session.
        if request.character_id!=(character if request.kind==PLACE else 0):
            raise ValueError('Нельзя выставлять отметки от имени другого игрока')
        if not battle['field'].inside(request.x,request.y):
            raise ValueError('Клетка отметки находится вне поля боя')
        now=self.tactical_wall()
        self.expire_tactical_marks(battle,now=now)
        marks=battle.setdefault('tactical_marks',{})
        if request.kind==PLACE:
            # FF identifies a mark by tile only in the original reader. Two
            # teammates' overlapping marks cannot be removed unambiguously.
            if any(author!=owner and battle['field'].allied(owner,author)
                   and (mark['x'],mark['y'])==(request.x,request.y)
                   for author,mark in marks.items()):
                raise ValueError('Эта клетка уже отмечена союзником')
        else:
            existing=marks.get(owner)
            if existing is None:return True
            if (existing['x'],existing['y'])!=(request.x,request.y):
                raise ValueError('Можно снять только свою текущую отметку')
        rates=battle.setdefault('tactical_mark_rate',{})
        samples=[stamp for stamp in rates.get(owner,()) if stamp>now-MARK_RATE_WINDOW_SECONDS]
        if len(samples)>=MARK_RATE_LIMIT:
            raise ValueError('Подождите перед следующей тактической отметкой')
        rates[owner]=[*samples,now]
        if request.kind==PLACE:
            marks[owner]=dict(x=request.x,y=request.y,expires_at_wall=now+NATIVE_TTL_SECONDS)
        else:del marks[owner]
        self._send_tactical_mark(battle,owner,request.kind,request.x,request.y)
        return True

    def expire_tactical_marks(self,battle,*,now=None):
        now=self.tactical_wall() if now is None else now
        marks=battle.get('tactical_marks',{})
        expired=tuple(author for author,mark in marks.items()
            if now>mark['expires_at_wall'] or not self._mark_member(battle,author))
        for author in expired:
            mark=marks.pop(author)
            if not battle['finished']:
                self._send_tactical_mark(battle,author,REMOVE,mark['x'],mark['y'])
        return expired

    def tactical_mark_packets(self,battle,viewer):
        """Rebuild only current allied marks after the reconnect member list.

        B2/07 has no remaining-lifetime field. Expiry pushes FF at the original
        authoritative deadline, including to a client currently reloading.
        """
        if battle['finished'] or not self._mark_member(battle,viewer):return ()
        now=self.tactical_wall()
        return tuple(encode_tactical_mark_notification(TacticalMark(PLACE,
            self.players[viewer].probe_character_id if author==viewer else author,
            mark['x'],mark['y']))
            for author,mark in sorted(battle.get('tactical_marks',{}).items())
            if self._mark_member(battle,author) and now<=mark['expires_at_wall']
            and battle['field'].allied(author,viewer))
