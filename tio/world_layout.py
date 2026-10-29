"""Saved map positions after the road layout moved every location (2026-10-29).

In-town characters stand at their town's parking point. Journeys started
before the move have no road path and point at old coordinates; they finish
at once at the relocated destination on the next refresh.
"""
import json

# Rectangles before the move; used only to recognise old journey targets.
LEGACY_BOUNDS = {
    2: (-390, -447, -345, -402), 3: (-171, -335, -136, -300), 4: (225, -437, 305, -357),
    5: (140, -70, 240, 30), 6: (-434, -370, -414, -350), 7: (315, -410, 335, -390),
    8: (286, -265, 366, -185), 9: (-90, -460, -64, -434), 10: (-330, 59, -304, 85),
    11: (63, -3, 83, 18), 12: (241, -175, 261, -155), 13: (-180, -284, -160, -264),
    14: (175, -346, 195, -326), 15: (88, -10, 108, 10), 16: (255, -170, 275, -150),
    17: (-25, -268, 1, -242), 18: (-150, 50, -90, 110), 19: (-240, -320, -220, -300),
    20: (-240, -420, -220, -400), 21: (-245, -370, -225, -350), 22: (110, -320, 130, -300),
}


def legacy_town_at(x, y):
    return next((town for town, (x1, y1, x2, y2) in LEGACY_BOUNDS.items()
                 if x1 <= x <= x2 and y1 <= y <= y2), None)


def _straight(x, y, tx, ty):
    return json.dumps([[x, y], [tx, ty]])


def normalize_characters(db, centers):
    """Idempotent: park in-town characters and finish journeys without a road path."""
    for town, (x, y) in centers.items():
        db.execute('UPDATE character_locations SET x=?,y=? WHERE town_id=? AND (x IS NOT ? OR y IS NOT ?)',
                   (x, y, town, x, y))
    for account, x, y, tx, ty, started in db.execute(
            'SELECT account,x,y,tx,ty,started FROM map_journeys WHERE path IS NULL').fetchall():
        town = legacy_town_at(tx, ty)
        if town in centers:
            tx, ty = centers[town]
        db.execute('UPDATE map_journeys SET tx=?,ty=?,arrives=?,path=? WHERE account=?',
                   (tx, ty, started, _straight(x, y, tx, ty), account))


def normalize_parties(db, centers):
    """Party journeys keep their target town; old ones arrive on the next refresh."""
    for party, x, y, tx, ty, started, town in db.execute(
            'SELECT party_id,x,y,tx,ty,started,town_id FROM travel_party_journeys WHERE path IS NULL').fetchall():
        if town in centers:
            tx, ty = centers[town]
        db.execute('UPDATE travel_party_journeys SET tx=?,ty=?,arrives=?,path=? WHERE party_id=?',
                   (tx, ty, started, _straight(x, y, tx, ty), party))

