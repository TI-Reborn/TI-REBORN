"""Local-only contracts retain marker IDs across public world extension."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tio.locations import TOWNS
from tio.pve_contracts import validate_catalog

ROOT=Path(__file__).resolve().parents[1]
PROPOSED={19:(-240,-320,-220,-300),20:(-240,-420,-220,-400),
          21:(-245,-370,-225,-350),22:(110,-320,130,-300)}


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
            for zone,bounds in ((18,TOWNS[18]),(20,TOWNS[20])):
                source=deepcopy(self.catalog)
                source['templates']=[{**source['templates'][0],'zone_id':zone,'bounds':list(bounds)}]
                with self.assertRaisesRegex(ValueError,'overlap'):validate_catalog(source)

    def test_geometry_still_reserved_with_different_id_and_safe_margin(self):
        with patch.dict(TOWNS,PROPOSED):
            for bounds in ((-150,50,-130,70),(-170,50,-160,70)):
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
