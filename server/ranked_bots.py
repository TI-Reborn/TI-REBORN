"""Transient TrueSkill seats, following Team/Wall's real-opponent policy."""
from tio.matchmaking import SearchTicket


def incomplete_groups(states,score):
    """Maximize admitted humans before filling two nonempty sides to four."""
    choices=[(sizes,groups) for sizes,groups in states.items() if all(sizes)]
    if not choices:return None
    def key(value):
        (a,b),groups=value
        means=[sum(score(t) for t in group)/len(group) for group in groups]
        return (-(a+b),abs(a-b),abs(means[0]-means[1]),
                tuple(sorted((t.joined_at,t.character_id) for g in groups for t in g)))
    return min(choices,key=key)[1]


def fill_seats(hub,seats,teams):
    """Copies reference owned actors but have no account, loadout or token claim."""
    used=set(hub.players)
    for battle in hub.battles.values():used.update(battle['room'].members)
    bots=set();identity=0x68000000
    real=tuple(seats)
    for side,team in enumerate(teams):
        sources=[s for s in real if s[1]==side and not s[5]]
        count=sum(len(s[4].actors) for s in sources)
        if not sources or not 1<=count<=4:raise ValueError('TrueSkill needs real players on both sides')
        for index in range(4-count):
            while identity in used:identity+=1
            if identity>=0x70000000:raise ValueError('Reserved bot owner range exhausted')
            source=sources[index%len(sources)];ticket=source[4];slot=index%len(ticket.actors)
            # Plain tickets deliberately omit RankedTicket flags/selections.
            copy=SearchTicket(identity,(ticket.actors[slot],),(ticket.levels[slot],),ticket.joined_at)
            seats.append((identity,side,source[2],source[3],copy,True))
            team.append(identity);bots.add(identity);used.add(identity);identity+=1
    return bots


def patrol(field,points):
    """Reachable flag-neighbour cells, never the blocked flag model itself."""
    goals=[]
    for cx,cy in (points.positions[2],*points.positions[:2]):
        cells=[(cx+dx,cy+dy) for dx,dy in ((-1,0),(0,-1),(0,1),(1,0))
               if field.inside(cx+dx,cy+dy) and (cx+dx,cy+dy) not in field.blocked]
        if cells:goals.append(min(cells))
    field.patrol_waypoints=tuple(goals)
