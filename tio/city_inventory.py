"""Complete city inventory reads using only real, account-owned snapshots.

The client can issue speculative or empty ItemList2F requests while refreshing
city menus. Native 2F sets global waiting; silently dropping a stale ID leaves
6B warehouse transfers blocked in the client. An existing primary snapshot
completes that read through the normal 30 consumer without fabricating the
missing fighter or showing a shop error. The lookup must be account-scoped.
State-changing actions validate their owners in their own handlers.
"""
from collections.abc import Callable, Iterable


def city_inventory_replies(
        requested: Iterable[int],
        lookup: Callable[[int], bytes | None],
) -> tuple[bytes, ...]:
    replies = []
    requested = tuple(requested)
    for owner in dict.fromkeys(requested):
        packet = lookup(owner)
        if packet is not None:
            replies.append(packet)
    if requested and not replies:
        primary = lookup(1)
        if primary is not None:
            replies.append(primary)
    return tuple(replies)
