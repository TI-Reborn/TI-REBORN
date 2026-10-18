"""Manual p57: independent accuracy per projectile, catalog damage per burst.

Integer shares preserve the catalog's full-burst endpoints, rather than
multiplying a weapon's advertised damage by its ammunition consumption.
Critical projectiles deal double damage (manual glossary); rounding and the
sector boundaries for piercing weapons are explicit emulator policy.
"""
from .combat_distance import combat_distance
from .visibility import field_sight


def burst(rng, low, high, accuracy, projectiles, critical_chance):
    total=0;landed=False;critical=False
    for index in range(projectiles):
        if rng.randrange(100)>=accuracy:continue
        landed=True
        full=rng.randint(low,high)
        share=full*(index+1)//projectiles-full*index//projectiles
        crit=share>0 and critical_chance>0 and rng.randrange(100)<critical_chance
        total+=share*(2 if crit else 1)
        critical=critical or crit
    return total,landed,critical


def line_victims(field, actor, target, maximum):
    dx,dy=target[0]-actor.x,target[1]-actor.y
    steps=max(abs(dx),abs(dy))
    cells={(actor.x+round(dx*i/steps),actor.y+round(dy*i/steps))
           for i in range(1,maximum+1)}
    return sorted((a for a in field._actors.values()
                   if a.actor_id!=actor.actor_id and a.health and (a.x,a.y) in cells
                   and combat_distance((actor.x,actor.y),(a.x,a.y))<=maximum
                   and field_sight(field,(actor.x,actor.y),(a.x,a.y))),
                  key=lambda a:(combat_distance((actor.x,actor.y),(a.x,a.y)),a.actor_id))


def area_victims(field, actor, target, maximum, radius=1):
    """Heavy burst through the chosen zone, independent of enemy visibility.

    Manual p39/p61 specifies spread and piercing, but no server geometry.
    Policy: the catalog radius is the half-width at the aimed distance;
    the sector continues to the catalog range. Integer dot/cross products
    keep boundaries deterministic for every observer and map orientation.
    """
    dx,dy=target[0]-actor.x,target[1]-actor.y
    length2=dx*dx+dy*dy
    if not length2:return []
    radius=max(0,radius)
    def inside(v):
        vx,vy=v.x-actor.x,v.y-actor.y
        dot=vx*dx+vy*dy
        cross=vx*dy-vy*dx
        return dot>0 and cross*cross*length2<=radius*radius*dot*dot
    return sorted((v for v in field._actors.values()
                   if v.actor_id!=actor.actor_id and v.health and inside(v)
                   and combat_distance((actor.x,actor.y),(v.x,v.y))<=maximum
                   and field_sight(field,(actor.x,actor.y),(v.x,v.y))),
                  key=lambda v:(combat_distance((actor.x,actor.y),(v.x,v.y)),v.actor_id))
