"""Native arena catalogue of supported, purchasable combat gear."""
from functools import lru_cache
from pathlib import Path
from .protocol.ranked import encode_gears


@lru_cache(maxsize=1)
def catalogue_packet():
    from .city_catalogs import CityCatalogs
    from .weapons import WeaponCatalog
    from .armor import ArmorCatalog
    shops=CityCatalogs(Path(__file__).resolve().parents[1]/'config/city_catalogs.json')
    sold={offer.item_id for offers in shops.items.values() for offer in offers}
    combat=set(WeaponCatalog().weapons)|set(ArmorCatalog().items)
    return encode_gears(sorted(sold & combat))
