"""Growing perk learning price shared by humans, dogs and miners.

The native AA reader takes prices from the server and no historical table is
known. Manual p45 fixes only the shape: every next rank is much dearer, and
every learned rank slightly raises all other perks. Coefficients are local
user-approved policy kept in config.
"""
from collections.abc import Mapping
from dataclasses import dataclass

WIRE_MAX = 0xffffffff


def _positive(value: object) -> bool:
    return type(value) is int and value > 0


@dataclass(frozen=True)
class PricePolicy:
    base_prices: Mapping[int, int]
    rank_multipliers: tuple[int, ...]
    surcharge_percent: int

    @classmethod
    def from_config(cls, data: Mapping) -> 'PricePolicy':
        try:
            bases = {int(k): v for k, v in data['base_prices'].items()}
        except (KeyError, ValueError, AttributeError) as error:
            raise ValueError('Invalid perk price policy') from error
        multipliers = tuple(data.get('rank_multipliers', ()))
        surcharge = data.get('surcharge_percent_per_learned_rank')
        if (not bases or not all(map(_positive, bases.values())) or not multipliers
                or not all(map(_positive, multipliers)) or type(surcharge) is not int or surcharge < 0):
            raise ValueError('Invalid perk price policy')
        return cls(bases, multipliers, surcharge)

    def price(self, ability: int, rank: int, learned_ranks: int) -> int:
        """learned_ranks is the sum of current ranks of this mercenary's perks."""
        if ability not in self.base_prices or not 1 <= rank <= len(self.rank_multipliers):
            raise ValueError('Perk rank has no price')
        if type(learned_ranks) is not int or learned_ranks < 0:
            raise ValueError('Invalid learned rank total')
        total = self.base_prices[ability] * self.rank_multipliers[rank-1] * (100 + self.surcharge_percent * learned_ranks)
        price = (total + 99) // 100
        if price > WIRE_MAX:
            raise ValueError('Perk price exceeds wire field')
        return price
