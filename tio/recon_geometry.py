"""Shared recon footprint; legacy binoculars retain their circular radius."""


def contains(effect, x, y):
    cx, cy = effect['center']; r = effect['radius']
    if effect.get('shape') == 'square':
        return max(abs(x-cx), abs(y-cy)) <= r
    return (x-cx)**2 + (y-cy)**2 <= r*r


def cells(field, effect):
    from .visibility import field_sight
    cx, cy = effect['center']; r = effect['radius']
    for y in range(max(0, cy-r), min(field.height, cy+r+1)):
        for x in range(max(0, cx-r), min(field.width, cx+r+1)):
            if not contains(effect, x, y): continue
            # Scope reveals all nine terrain surfaces, including obstacles.
            # Actor sight still checks smoke and wall rays separately.
            if effect.get('shape') == 'square' or (
                    (x, y) not in field.blocked and field_sight(field, (cx, cy), (x, y))):
                yield x, y
