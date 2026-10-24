"""Shared dismissal eligibility; provenance does not determine ownership."""
from collections.abc import Sequence
from .protocol.item_list import ItemRecord


class DismissalRejected(ValueError):
    """A saved fighter cannot currently leave the roster."""


def require_dismissable(pet_id: int, items: Sequence[ItemRecord]) -> None:
    if type(pet_id) is not int or pet_id <= 1:
        raise DismissalRejected('Основного бойца нельзя уволить')
    if items:
        raise DismissalRejected('Сначала освободите инвентарь увольняемого бойца')
