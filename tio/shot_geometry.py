"""TI CanTraceCells (ti.exe 6E1C88, legacy mode) sight rays in 32-unit cells."""


def _intersects(start,end,cell):
    """Closed segment/rectangle intersection; touching a wall blocks this ray."""
    lower,upper=0.,1.
    for origin,finish,tile in zip(start,end,cell):
        delta=finish-origin;lo=tile*32;hi=lo+32
        if delta==0:
            if not lo<=origin<=hi:return False
        else:
            a,b=(lo-origin)/delta,(hi-origin)/delta
            lower=max(lower,min(a,b));upper=min(upper,max(a,b))
            if lower>upper:return False
    return True


def clear_shot(start,end,opaque):
    if start==end:return True
    source=tuple(v*32+16 for v in start);target=tuple(v*32+16 for v in end)
    # Native checks centre, four source offsets, then four target offsets.
    rays=[(source,target)]
    for dx,dy in ((0,-12),(0,12),(12,0),(-12,0)):
        rays.append(((source[0]+dx,source[1]+dy),target))
        rays.append((source,(target[0]+dx,target[1]+dy)))
    nearby=[p for p in opaque if min(start[0],end[0])<=p[0]<=max(start[0],end[0])
            and min(start[1],end[1])<=p[1]<=max(start[1],end[1])]
    return any(not any(_intersects(a,b,p) for p in nearby) for a,b in rays)
