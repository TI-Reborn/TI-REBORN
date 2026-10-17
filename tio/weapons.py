"""Server combat metadata recovered from the legacy client items.cfg."""
from dataclasses import dataclass
import json
import struct
from pathlib import Path
from fractions import Fraction
from functools import lru_cache


def _extended(value):
    """Round a rational to the x87 64-bit significand (nearest, ties even)."""
    if not value:return Fraction(0)
    sign=-1 if value<0 else 1
    value=abs(value)
    exponent=value.numerator.bit_length()-value.denominator.bit_length()
    power=Fraction(2)**exponent
    if value<power:exponent-=1
    quantum=Fraction(2)**(exponent-63)
    return sign*round(value/quantum)*quantum


@lru_cache(maxsize=8192)
def _range_endpoint(value,fade,offset,span):
    # Preserve the native operation order, including extended rounding before
    # Trunc. Algebraic rational simplification gives Spas 57 instead of 56.
    loss=_extended(1-_extended(Fraction(fade,100)))
    loss=_extended(loss*value)
    loss=_extended(loss*offset)
    loss=_extended(loss/span)
    return max(0,int(_extended(value-loss)))


@dataclass(frozen=True)
class WeaponStats:
    template_id: int
    name: str
    weapon_type: str
    damage_base: int
    damage_random: int
    attack_ap: int
    reload_ap: int | None
    ammo_id: int | None
    bullets_count: int
    min_range: int
    max_range: int


class WeaponCatalog:
    def __init__(self,path=None):
        path=path or Path(__file__).resolve().parents[1]/'config/weapon_catalog.json'
        data=json.loads(Path(path).read_text(encoding='utf-8'))
        self.ammunition={int(i):r for i,r in data['ammunition'].items()}
        self.sources={int(i):r['source_fields'] for i,r in data['weapons'].items()}
        self.npc_defaults={int(i):int(w) for i,w in data.get('npc_default_weapons',{}).items()}
        self.weapons={int(i):WeaponStats(template_id=int(i),**{k:v for k,v in r.items() if k!='source_fields'})
                      for i,r in data['weapons'].items()}
        for w in self.weapons.values():
            if w.attack_ap<=0 or min(w.damage_base,w.damage_random,w.min_range,w.max_range)<0:
                raise ValueError('Invalid weapon values')
            if w.ammo_id is not None and w.ammo_id not in self.ammunition:raise ValueError('Unknown ammunition')

    def accepts_ammo(self,weapon_id,ammo_id):
        weapon=self.weapons[weapon_id]
        return weapon.ammo_id is not None and weapon.ammo_id==ammo_id

    def accuracy(self, weapon_id, distance, bonus=0):
        """TSItem.GetAccuracy (a7ad00), then actor bonus and the manual's cap.

        The native ratio is stored as Single before the final x87 Round.
        accuracy_coeff is a legacy field, not used by this client function.
        """
        w=self.weapons[weapon_id];source=self.sources[weapon_id]
        span=w.max_range-w.min_range
        ratio=struct.unpack('<f',struct.pack('<f',(distance-w.min_range)/span))[0] if span>0 else 1.0
        chance=round(int(source.get('accuracy',100))+(1-ratio)*int(source.get('accuracy_gain_amount',0)))
        return max(0,min(95,chance+bonus))

    def distance_damage(self, weapon_id, distance, enhancement=0):
        """Native a7a576..a7a67f: range scaling before skill and armor.

        Returns the base interval; special burst/explosion effects are separate.
        Distance zero is the client's generic, untargeted tooltip interval.
        """
        w=self.weapons[weapon_id];source=self.sources[weapon_id]
        low,high=w.damage_base+enhancement,w.damage_base+w.damage_random+enhancement
        if distance==0:return low,high
        span=max(1,w.max_range-w.min_range)
        offset=distance if source.get('weaponAttack')=='Minigun' else distance-w.min_range
        fade=int(source.get('damage_fade',100))
        return tuple(_range_endpoint(value,fade,offset,span) for value in (low,high))

    def equipped(self,inventory_packet,*,human,resource=None):
        if not human:return (self.weapons[self.npc_defaults.get(resource,333)],)
        from .protocol.item_list import decode_item_list
        owner,items,_=decode_item_list(inventory_packet)
        weapons=tuple(self.weapons[i.template_id] for i in items
                      if i.equipped==1 and i.client_slot==16 and i.template_id in self.weapons)
        # Client mobs.udf default weapons: human fists300, dog fangs333.
        return weapons or (self.weapons[337 if resource==6 else 300 if human else 333],)
