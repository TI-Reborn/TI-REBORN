"""Read-only public character projection. Never returns wallets or credentials."""
from contextlib import closing
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
import sqlite3

from tio.protocol.pet_info import decode_pet_info
from tio.character_lifecycle import retired


@dataclass(frozen=True)
class PublicProfile:
    name: bytes
    level: int
    soldiers: int
    wins: int
    losses: int
    draws: int
    kills: int = 0
    deaths: int = 0
    damage_dealt: int = 0
    damage_received: int = 0
    rating: int = 0
    squad_rank: int = 0
    squad_icon: int = 0
    online_seconds: float = 0
    mercenaries: tuple = ()
    skill: int = 0
    league: int = 3
    place: int = 0
    streak: int = 0
    clan_name: bytes = b''
    clan_id: int = 0
    alliance_name: bytes = b''
    alliance_id: int = 0
    clan_crest_id: int = 0
    alliance_crest_id: int = 0

    summary: str = ''
    website: str = ''
    contact: str = ''
    avatar_id: int = 0
    jailed: bool = False
    assault_place: int = 0
    assault_bonus: int = 0
    tournament_places: tuple[int, ...] = (0,) * 8


def read_profile(path: str | Path, *, account: str | None = None, name: bytes | None = None,
                 include_history: bool = True) -> PublicProfile | None:
    # A UI refresh must never run rank decay or create/modify game tables.
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)) as db:
        db.execute('BEGIN')
        if name is not None:
            row=db.execute('SELECT account,name FROM characters WHERE name_key=?',(name.decode('ascii').lower(),)).fetchone()
        else:
            row=db.execute('SELECT account,name FROM characters WHERE account=? ORDER BY slot LIMIT 1',(account,)).fetchone()
        if row is None:return None
        owner,character_name=row
        if retired(db, owner):return None
        from tio.clans import membership
        clan=membership(db,owner)
        from tio.alliances import alliance_for_clan
        alliance=alliance_for_clan(db,clan['id']) if clan else None
        from tio.clan_benefits import crest_id
        clan_crest=crest_id(db,clan['id']) if clan else 0
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        roster=db.execute('SELECT human,pet_packet FROM owned_pets WHERE account=? ORDER BY pet_id',(owner,)).fetchall() if 'owned_pets' in tables else []
        fields=[decode_pet_info(packet,human_equipment=bool(human)).fields for human,packet in roster]
        levels=[f['0x8c4aef'] for f in fields]
        results=dict(db.execute('SELECT result,COUNT(*) FROM battle_rewards WHERE account=? GROUP BY result',(owner,))) if include_history and 'battle_rewards' in tables else {}
        totals=(0,0,0,0);rating=0;seconds=0;rank=0
        if include_history:
            if 'player_battle_statistics' in tables:
                totals=db.execute('''SELECT COALESCE(SUM(kills),0),COALESCE(SUM(deaths),0),
                    COALESCE(SUM(damage_dealt),0),COALESCE(SUM(damage_received),0)
                    FROM player_battle_statistics WHERE account=?''',(owner,)).fetchone()
            old_kills=0
            if 'player_statistics_baselines' in tables:
                baseline=db.execute('SELECT kills FROM player_statistics_baselines WHERE account=?',(owner,)).fetchone()
            else:baseline=None
            if baseline is not None:old_kills=baseline[0]
            elif 'achievement_counters' in tables:
                counter=db.execute("SELECT value FROM achievement_counters WHERE account=? AND metric='kills'",(owner,)).fetchone()
                if counter:old_kills=counter[0]
            totals=(totals[0]+old_kills,*totals[1:])
            if 'soldier_ratings' in tables:
                rating=db.execute('''SELECT COALESCE(SUM(s.rating),0) FROM soldier_ratings s
                    JOIN owned_pets p ON p.account=s.account AND p.pet_id=s.pet_id WHERE s.account=?''',(owner,)).fetchone()[0]
            from tio.achievement_benefits import total_rating
            rating=total_rating(db,owner,rating)
            if 'player_online' in tables:
                row=db.execute('SELECT seconds FROM player_online WHERE account=?',(owner,)).fetchone()
                if row:seconds=row[0]
            from tio.ranks import signed,rank_id
            points=[signed(f['0x8c4bd0']) if 1<=f['0x8c4bbc']<=29 else 0 for f in fields]
            top=set(sorted(range(len(fields)),key=lambda i:(-levels[i],i))[:3])
            rank=int(sum((Fraction(p,3 if i in top or p<0 else 15) for i,p in enumerate(points)),Fraction(0)))
            commander=rank_id(points[0]) if points else 1
            mercenaries=tuple((f['0x8c4489'],f['0x8c4aef'],f['0x8c4b05'],min(rank_id(p),commander)) for f,p in zip(fields,points))
        else:mercenaries=()
        icon=min(14,max(0,(rank-1)//2500))
        from tio.ranked import profile as ranked_profile
        skill,league,place,streak=ranked_profile(db,owner) if include_history else (0,3,0,0)
        texts = ('', '', '')
        avatar_id = 0
        jailed = False
        badge = (0, 0)
        if include_history:
            from tio.player_profile_text import read as read_text
            from tio.world_completion import prison_state
            texts = read_text(db, owner)
            if 'pet_avatars' in tables:
                avatar = db.execute('SELECT avatar_id FROM pet_avatars WHERE account=? AND pet_id=1',
                                    (owner,)).fetchone()
                avatar_id = avatar[0] if avatar else 0
            state = prison_state(db, owner)
            jailed = bool(state and state['remaining'] > 0)
            if clan:
                from tio.clan_benefits import active_weekly_badge
                badge = active_weekly_badge(db, clan['id'])
        from tio.tournaments import read_standings
        places = read_standings(db, owner) if include_history else (0,) * 8
        return PublicProfile(bytes(character_name),min(255,max(levels,default=0)),len(roster),
                             results.get(1,0),results.get(0,0),results.get(2,0),
                             *totals,rating,rank,icon,seconds,mercenaries,skill,league,place,streak,
                             clan['name'] if clan else b'',clan['id'] if clan else 0,
                             alliance['name'] if alliance else b'',alliance['id'] if alliance else 0,
                             clan_crest,alliance.get('crest_id',0) if alliance else 0,
                             *texts,avatar_id,jailed,*badge,places)


def prisoner_card(path: str | Path, name: bytes) -> bytes:
    from tio.protocol.public_profile import encode_jail_info
    from tio.world_completion import prison_state

    with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('BEGIN')
        row = db.execute('SELECT account,name FROM characters WHERE name_key=?',
                         (name.decode('ascii').lower(),)).fetchone()
        state = prison_state(db, row[0]) if row and not retired(db, row[0]) else None
        if not state or not state['remaining']:
            raise ValueError('Персонаж не отбывает наказание')
        return encode_jail_info(bytes(row[1]), state['remaining'])
