"""Fixed-pair team standings through ordinary native Team battle and chat.

BA/C8 mode 1 already assembles two real players per side, each with up to
three soldiers. C6 remains the separate duel screen; no unsupported team
selector or historical seasonal packet is invented.
"""
from contextlib import closing
from datetime import datetime, timezone
import time

from tio.db_transaction import connect
from tio import rating_seasons, team_ratings, rating_completion
from tio.protocol.chat import encode_system_message


def _messages(lines,channel=0):
    return tuple(encode_system_message(channel,b'TIO',line[:195]) for line in lines)


def command(session,text,*,channel=0,now=None):
    """Private native chat replies; never broadcast account IDs or aliases."""
    words=text.strip().split()
    if not words or words[0].lower() not in ('!teamrating','!seasons'):return None
    if getattr(session,'database',None) is None:raise ValueError('Рейтинг доступен после входа в игру')
    now=time.time() if now is None else now
    if words[1:2]==['wall']:
        return wall_command(session,words,channel=channel,now=now)
    with closing(connect(session.database)) as db,db:
        db.execute('BEGIN IMMEDIATE');team_ratings.schema(db)
        current,_,_=rating_seasons.current(db,now)
        if words[0].lower()=='!seasons':
            if len(words)!=1:raise ValueError('Команда: !seasons')
            rows=rating_seasons.listing(db)
            labels={'open':'идёт','closing':'ждёт завершения боёв','archived':'архив'}
            lines=['Сезоны командного рейтинга; границы месяца — 00:00 UTC.']
            for row in rows:
                end=datetime.fromtimestamp(row['ends_at'],timezone.utc).strftime('%d.%m %H:%M UTC')
                lines.append(f"{row['id']}: {labels[row['state']]}, конец {end}.")
            lines.append('Таблица: !teamrating; архив: !teamrating ГГГГ-ММ; всё время: !teamrating all.')
        else:
            if len(words)>3:raise ValueError('Команда: !teamrating [ГГГГ-ММ|all] [страница]')
            scope=words[1] if len(words)>=2 else current
            if scope!='all':rating_seasons.validate(scope)
            try:page=int(words[2]) if len(words)==3 else 1
            except ValueError as exc:raise ValueError('Страница должна быть числом') from exc
            if not 1<=page<=100:raise ValueError('Страница должна быть от 1 до 100')
            rows=team_ratings.standings(db,scope=scope,offset=(page-1)*10,limit=10)
            lines=[f'Командный рейтинг {scope}, страница {page}. Фиксированные пары, бой 2 на 2.']
            if not rows:lines.append('На этой странице пока нет завершённых зачётных боёв.')
            for row in rows:
                names=' + '.join(row['names'])
                lines.append(f"{row['place']}. {names}: {row['skill']} очков; В/П/Н {row['wins']}/{row['losses']}/{row['draws']}.")
    return _messages(lines,channel)


def wall_command(session,words,*,channel,now):
    with closing(connect(session.database)) as db,db:
        db.execute('BEGIN IMMEDIATE');rating_completion.schema(db)
        current,_,_=rating_completion.current(db,now)
        if words[0].lower()=='!seasons':
            if len(words)!=2:raise ValueError('Команда: !seasons wall')
            rows=rating_completion.seasons(db)
            labels={'open':'идёт','closing':'ждёт завершения боёв','archived':'архив'}
            lines=['Сезоны стенки 4 на 4: месяц UTC; денежные и предметные призы не назначены.']
            lines.extend(f"{row['id']}: {labels[row['state']]}." for row in rows)
        else:
            if len(words)>4:raise ValueError('Команда: !teamrating wall [ГГГГ-ММ|all] [страница]')
            scope=words[2] if len(words)>=3 else current
            try:page=int(words[3]) if len(words)==4 else 1
            except ValueError as exc:raise ValueError('Страница должна быть числом') from exc
            if not 1<=page<=100:raise ValueError('Страница должна быть от 1 до 100')
            dto=rating_completion.public_listing(db,format='wall',scope=scope,offset=(page-1)*10,now=now)
            lines=[f'Рейтинг стенки {scope}, страница {page}. Постоянные четвёрки, бой 4 на 4.']
            if not dto['rows']:lines.append('На этой странице пока нет завершённых зачётных боёв.')
            for row in dto['rows']:
                lines.append(f"{row['place']}. {' + '.join(row['names'])}: {row['skill']} очков; В/П/Н {row['wins']}/{row['losses']}/{row['draws']}.")
    return _messages(lines,channel)


def backend(frozen):
    if frozen.get('version')==1:return team_ratings
    if frozen.get('version')==2 and frozen.get('format')=='wall':return rating_completion
    raise ValueError('Unknown team rating report version')


class TeamRanked:
    def team_rating_clock(self):
        journal=getattr(self,'journal',None)
        return journal.wall() if journal is not None else time.time()

    def freeze_team_rating(self,battle,seats,teams,first):
        """After squad validation, before consume, in the match birth unit."""
        players=2 if first.mode==1 else 4 if first.mode==4 else 0
        if (not players or battle.get('kind') in ('mine','assault','survival') or
            battle.get('bots') or len(seats)!=players*2 or len(teams)!=2 or any(len(team)!=players for team in teams)):
            return False
        implementation=team_ratings if players==2 else rating_completion
        rules=implementation.policy()
        if any(bot or not 1<=len(ticket.actors)<=rules['maximum_soldiers'] or
               any(not rules['minimum_level']<=level<=rules['maximum_level'] for level in ticket.levels)
               for _,_,_,_,ticket,bot in seats):return False
        paths={str(path) for _,_,path,_,_,_ in seats}
        if len(paths)!=1:raise ValueError('Командный рейтинг требует общую базу данных')
        lookup={owner:account for owner,_,_,account,_,_ in seats}
        accounts=tuple(tuple(lookup[owner] for owner in team) for team in teams)
        with closing(connect(next(iter(paths)))) as db,db:
            db.execute('BEGIN IMMEDIATE')
            frozen=implementation.admit(db,battle['match_id'],accounts,now=self.team_rating_clock())
        battle['team_rating_frozen']=frozen
        return True

    def finish_team_rating(self,battle):
        """Freeze final rating report before any reward outbox job is written."""
        frozen=battle.get('team_rating_frozen')
        if frozen is None:return None
        if 'team_rating_final' in battle:return battle['team_rating_final']
        field=battle['field']
        alive={field.teams[actor.owner_id] for actor in field._actors.values() if actor.health is not None and actor.health>0}
        if len(alive)>1:raise ValueError('Team rating battle is still in progress')
        winner=next(iter(alive)) if alive else None
        sides={side for owner,(_,_,side) in battle['reward_roster'].items() if owner in battle.get('reward_damage',())}
        if not battle.get('reward_started'):sides=set()
        value=backend(frozen).report(frozen,winner,sides)
        # Pure dictionaries/tuples survive the allowlisted battle checkpoint.
        battle['team_rating_final']=value
        return value

    def team_rating_report(self,battle):return battle.get('team_rating_final')

    def cancel_team_rating(self,battle,reason):
        frozen=battle.get('team_rating_frozen')
        if frozen is None:return False
        accounts=[name for team in frozen['teams'] for name in team]
        session=next((s for s in self.players.values() if s.account in accounts),None)
        if session is None:
            journal=getattr(self,'journal',None)
            path=journal.path if journal is not None else None
        else:path=session.database
        if path is None:raise ValueError('Team rating cancellation database missing')
        with closing(connect(path)) as db,db:
            db.execute('BEGIN IMMEDIATE')
            return backend(frozen).void(db,battle['match_id'],reason,now=self.team_rating_clock())

    def team_rating_announcements(self,battle,owner):
        frozen=battle.get('team_rating_frozen')
        if frozen is None:return ()
        if frozen.get('format')=='wall':
            return _messages((f"Рейтинг стенки 4 на 4: сезон {frozen['season']}. Постоянные четвёрки.",
                              'Зачёт требует урона обеих сторон; призы сезона не назначены. Таблица: !teamrating wall.'))
        return _messages((f"Командный рейтинг: сезон {frozen['season']}. Пара сохраняется по двум участникам.",
                          'Зачёт требует урона от обеих сторон; повторные противники ограничены. Таблица: !teamrating.'))


def reconcile_pending(path,retained_matches,*,now=None):
    """After checkpoint/outbox recovery, void only matches with no durable state.

The caller supplies all retained battle and settlement match IDs. A pending
reward report must be included even when its battle checkpoint has ended.
"""
    retained=set(retained_matches)
    with closing(connect(path)) as db,db:
        db.execute('BEGIN IMMEDIATE');voided=[]
        for table,implementation in (('team_ranked_matches',team_ratings),('wall_ranked_matches',rating_completion)):
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name=?",(table,)).fetchone():continue
            for (match,) in db.execute("SELECT match_id FROM "+table+" WHERE state='pending'").fetchall():
                if match not in retained:
                    implementation.void(db,match,'recovery_missing',now=now);voided.append(match)
        return tuple(voided)
