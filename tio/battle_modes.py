"""Classic arena formats (manual p14); player limits and training turn policy.

Survival admits two to four independent owners, with one to three actors each.
Team turns alternate owners A1/B1/A2/B2; each owner controls their squad.
Wall alternates A1/B1/.../A4/B4, exactly one actor per owner.
The first side and teammate order are local policy, not recovered server code.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class BattleMode:
    code: int
    players: int
    max_soldiers: int
    max_players: int | None = None

    def __post_init__(self):
        # `players` remains the legacy training scene's fixed seat count.
        if self.max_players is None:object.__setattr__(self,'max_players',self.players)

    @property
    def min_players(self):return self.players

    def validate(self, count):
        if not 1 <= count <= self.max_soldiers:
            raise ValueError('Choose exactly one fighter for Wall' if self.code == 4
                             else 'Select one to three fighters')

    def validate_players(self, count):
        if type(count) is not int or not self.min_players <= count <= self.max_players:
            raise ValueError('Survival requires two to four players' if self.code == 0
                             else 'Incorrect number of battle participants')


MODES = {0: BattleMode(0, 2, 3, 4), 1: BattleMode(1, 4, 3), 4: BattleMode(4, 8, 1), 7: BattleMode(7, 2, 3)}


def mode_rules(code):
    if code not in MODES:
        raise ValueError('Unsupported classic battle mode')
    return MODES[code]


def level_band(level):
    for index, ceiling in enumerate((3, 6, 10, 15, 20)):
        if 1 <= level <= ceiling:
            return index
    raise ValueError('Unsupported classic arena level')
