"""Explicit local catalog policy; wire unknowns remain named as unknowns.

Ordinary-shop purchases use tio.shop; replenished hiring uses tio.hiring.
The separate service menu remains incomplete.
"""
import json
from .protocol.premium_shop import PremiumItem, encode_premium_shop
from pathlib import Path
from .protocol.city_catalogs import (ShopItem, HireCandidate, ServiceOffer, ServiceOption,
    encode_item_shop, encode_pet_shop, encode_service_shop)


class CityCatalogs:
    def __init__(self, path: Path):
        data = json.loads(path.read_text(encoding='utf-8'))
        self.warehouse_capacity = data['warehouse_capacity']
        if type(self.warehouse_capacity) is not int or self.warehouse_capacity < 1:
            raise ValueError('Positive local warehouse capacity required')
        self.items = {int(category): tuple(ShopItem(**item) for item in items)
                      for category, items in data['item_categories'].items()}
        self.premium_items = tuple(PremiumItem(**row) for row in data.get('premium_items', ()))
        self.price_revision = data.get('price_revision', 0)
        if len({o.offer_id for o in self.premium_items}) != len(self.premium_items):
            raise ValueError('Duplicate Premium offer ID')
        if any(o.gold <= 0 or o.pack_count <= 0 for o in self.premium_items):
            raise ValueError('Premium prices and packs must be positive')
        self.premium_shop(0)
        self.candidates = tuple(HireCandidate(
            **{**candidate, 'name': candidate['name'].encode('cp1251'),
               'optional_bytes': bytes(candidate['optional_bytes']) if candidate['optional_bytes'] is not None else None,
               'stat_float_bits': tuple(candidate['stat_float_bits'])})
            for candidate in data['hire_candidates'])
        self.services = tuple(ServiceOffer(offer['unknown_u32'], offer['unknown_u8'],
            tuple(ServiceOption(**option) for option in offer['options'])) for offer in data['service_offers'])
        # Fail before opening a session if configuration cannot be serialized.
        for category in self.items:
            self.item_shop(category)
        self.pet_shop()
        self.pet_shop(9)
        self.service_shop()

    def item_shop(self, category, *, discounted=False):
        from dataclasses import replace
        items=self.items.get(category, ())
        if discounted:items=tuple(replace(o,unknown_u32_03=(o.unknown_u32_03*4+4)//5) for o in items)
        return encode_item_shop(category, items)

    def premium_shop(self, category, *, discounted=False):
        from dataclasses import replace
        items=self.premium_items if category in (0, 1) else ()
        if discounted:items=tuple(replace(o,gold=(o.gold*4+4)//5) for o in items)
        return encode_premium_shop(category, self.price_revision,items)

    def pet_shop(self, town=3):
        return encode_pet_shop(tuple(c for c in self.candidates if (c.resource_type==6)==(town==9)))

    def service_shop(self):
        return encode_service_shop(self.services)
