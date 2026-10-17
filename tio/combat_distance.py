"""Native a8907c: round(sqrt(dx*dx+dy*dy)), not a strict circular boundary."""
from math import isqrt


def combat_distance(start,end):
    squared=sum((a-b)**2 for a,b in zip(start,end))
    floor=isqrt(squared)
    # An integer squared distance cannot produce an exact half-integer root.
    return floor+int(4*squared>(2*floor+1)**2)
