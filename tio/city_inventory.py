"""Answer city inventory lookups for owners that still exist.

The client can issue speculative or empty ItemList2F requests while refreshing
city menus. A missing owner is a stale read, not a failed player action; turning
it into F0/394 displays a chat error for every queried ID (notably on hire-market
open). State-changing actions validate their owners in their own handlers.
"""


def city_inventory_replies(requested, lookup):
    replies = []
    requested = tuple(requested)
    for owner in dict.fromkeys(requested):
        packet = lookup(owner)
        if packet is not None:
            replies.append(packet)
    return tuple(replies)
