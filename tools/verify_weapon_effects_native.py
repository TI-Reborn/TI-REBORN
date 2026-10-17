"""Original ammo metadata stores and ability27 writer; rendering is not emulated."""
from verify_weapon_consume_native import run as consume
from verify_ability_cast_native import run as cast
from verify_auth_native import ROOT,EXPECTED_SHA,json
from tio.protocol.ability_cast import AbilityCast
from tio.weapons import WeaponCatalog
import xml.etree.ElementTree as ET


def main():
    catalog=WeaponCatalog();items=ET.parse(ROOT/'evidence/items_diagnostic.xml').getroot()
    cases=[]
    for weapon,ammo,count in ((314,14,20),(315,14,30),(316,8,1),(340,340,1)):
        node=items.find(f"item[@id='{weapon}']/for/consume")
        assert (int(node.get('id')),int(node.get('amount')))==(ammo,count)
        if weapon!=340:
            assert (catalog.weapons[weapon].ammo_id,catalog.weapons[weapon].bullets_count)==(ammo,count)
        cases.append(dict(weapon=weapon,**consume(ammo,count)))
    packet=cast(AbilityCast(27,17,0,8,9))
    report=dict(sha256=EXPECTED_SHA,method=__doc__,ammo=cases,subgrenade_request=packet)
    (ROOT/'evidence/weapon_effects_native.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Original weapon consume bindings and ability27 request: 5 cases PASS')

if __name__=='__main__':main()
