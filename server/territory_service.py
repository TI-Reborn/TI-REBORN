"""Project durable claims and UTC windows into the original TownInfo branch."""
from contextlib import closing
from tio.db_transaction import connect
from tio.protocol.town_info import encode_town_info
from tio.protocol.assault import ZoneInfo,ClanOwner,encode_zone_body

PHASES={'WAIT_ASSAULT':0,'REGISTRATION':1,'TOUR1':2,'TOUR2_PAUSE':3,'TOUR2':4,'TOUR3_PAUSE':5,'TOUR3':6,'FINISHED':0}


def encode_zone_info(base,state,*,now,path):
    event=state['event'];owner=None
    if state['claim']['owner_clan'] is not None:
        with closing(connect(path)) as db:
            row=db.execute('SELECT name,leader FROM clans WHERE id=?',(state['claim']['owner_clan'],)).fetchone()
            if row:
                char=db.execute('SELECT name FROM characters WHERE account=? ORDER BY slot LIMIT 1',(row[1],)).fetchone()
                from tio.clan_benefits import crest_id
                owner=ClanOwner(state['claim']['owner_clan'],bytes(row[0]),bytes(char[0]) if char else b'',
                                crest_id(db,state['claim']['owner_clan']))
    lo,hi=state['levels']
    cap=state.get('max_upgrade',{6:10,10:15,15:20,20:25}.get(hi,25))
    zone=ZoneInfo(PHASES[event['phase']],now,event['starts'],event['phase_ends'],lo,hi,lo,hi,cap,
        event['starts']+event['rules']['period_seconds'],owner)
    # The first six branches are absent. Seventh branch is Assault4ZoneInfo.
    raw=encode_town_info(base)
    return raw[:-2]+b'\x01'+encode_zone_body(zone)+raw[-1:]
