"""Bound the legacy EndTurn tail; its packet contains no turn identifier."""

END_TURN_REPEAT_SECONDS = 1.0


def within_end_turn_repeat(deadline: float, now: float) -> bool:
    """Ignore only a recent completion, never a stale/future clock origin."""
    return now < deadline <= now + END_TURN_REPEAT_SECONDS
