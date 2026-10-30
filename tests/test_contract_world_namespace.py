"""Local-only contracts retain marker IDs across public world extension."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tio.locations import TOWNS
from tio.pve_contracts import validate_catalog

ROOT=Path(__file__).resolve().parents[1]
# Training bases of the road-layout map (2026-10-29).
PROPOSED={town:TOWNS[town] for town in (19,20,21,22)}


class ContractWorldNamespaceTests(unittest.TestCase):
    def setUp(self):
        self.catalog=json.loads((ROOT/'config/pve_contracts.json').read_text(encoding='utf-8'))

    def test_private_shared_ids_allowed_without_changing_catalog_or_world(self):
        old=deepcopy(self.catalog);towns=dict(TOWNS)
        with patch.dict(TOWNS,PROPOSED):
            result=validate_catalog(self.catalog)
            self.assertEqual([t['zone_id'] for t in result['templates']],[18,19,20])
            self.assertEqual(result,self.catalog)
            self.assertEqual(TOWNS[18],(-150,50,-90,110))
            self.assertEqual(result['templates'][0]['bounds'],[-290,-245,-270,-225])
        self.assertEqual(self.catalog,old);self.assertEqual(TOWNS,towns)

    def test_matching_public_id_with_conflicting_geometry_is_rejected(self):
        with patch.dict(TOWNS,PROPOSED):
            for zone in (18,20):
                x1,y1=TOWNS[zone][:2]
                source=deepcopy(self.catalog)
                source['templates']=[{**source['templates'][0],'zone_id':zone,'bounds':[x1,y1,x1+20,y1+20]}]
                with self.assertRaisesRegex(ValueError,'overlap'):validate_catalog(source)

    def test_geometry_still_reserved_with_different_id_and_safe_margin(self):
        with patch.dict(TOWNS,PROPOSED):
            # Inside Detroit, then just within the safe margin west of it.
            for bounds in ((-150,200,-130,220),(-190,200,-175,220)):
                source=deepcopy(self.catalog)
                source['templates']=[{**source['templates'][0],'zone_id':250,'bounds':list(bounds)}]
                with self.assertRaisesRegex(ValueError,'overlap'):validate_catalog(source)

    def test_duplicates_inside_private_namespace_remain_rejected(self):
        with patch.dict(TOWNS,PROPOSED):
            source=deepcopy(self.catalog);source['templates'][1]['zone_id']=18
            with self.assertRaisesRegex(ValueError,'Duplicate'):validate_catalog(source)

    def test_proposed_training_geometry_has_safe_margin_and_preserves_old_routes(self):
        static={str(k):v for k,v in TOWNS.items() if k not in PROPOSED}
        static.update({'contract:'+r['id']:tuple(r['bounds']) for r in self.catalog['templates']})
        for town,(x1,y1,x2,y2) in PROPOSED.items():
            peers={**static,**{str(k):v for k,v in PROPOSED.items() if k!=town}}
            for label,(a,b,c,d) in peers.items():
                with self.subTest(town=town,other=label):
                    self.assertFalse(x1<=c+15 and x2>=a-15 and y1<=d+15 and y2>=b-15)
        for x,y in ((-220,-280),(-230,-270)):
            self.assertFalse(any(a<=x<=c and b<=y<=d for a,b,c,d in PROPOSED.values()))


if __name__=='__main__':unittest.main()
