"""World source preservation, native metadata and bounded geometry checks."""
from copy import deepcopy
import hashlib
import json
import sys
from pathlib import Path
import tempfile
import unittest

from tools import prepare_world_completion_catalog as tool


class WorldCatalogueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=(tool.FOLDER/'client/source/zones.xml').read_bytes()
        cls.server=(tool.FOLDER/'source/zones_diagnostic.xml').read_bytes()
        cls.policy=json.loads(tool.POLICY.read_bytes())

    def test_foreign_rows_preserved_from_each_distinct_actual_source(self):
        for raw in (self.source,self.server):
            new=tool.merge(raw,self.policy)
            before={int(m[1]):m[0] for m in tool.ROW.finditer(raw)}
            after={int(m[1]):m[0] for m in tool.ROW.finditer(new)}
            self.assertEqual(list(after),list(range(1,23)))
            self.assertEqual([i for i in before if before[i]!=after[i]],[4,7,10])
            self.assertTrue(all(before[i]==after[i] for i in before if i not in tool.CHANGED))
        client=tool.rows(tool.merge(self.source,self.policy),22)
        runtime=tool.rows(tool.merge(self.server,self.policy),22)
        self.assertEqual(tool.values(client[2])['minlevel'],'3')
        self.assertEqual(tool.values(runtime[2])['minlevel'],'4')
        self.assertEqual(tool.values(client[6])['enabled'],'0')
        self.assertEqual(tool.values(runtime[6])['enabled'],'1')

    def test_manual_world_rules_use_original_native_xml_keys(self):
        nodes=tool.rows(tool.merge(self.source,self.policy),22)
        self.assertEqual(tool.values(nodes[4])['minlevel'],'4')
        self.assertEqual(tool.values(nodes[4])['dragin'],'false')
        self.assertEqual(tool.values(nodes[7])['x1'],'315')
        self.assertEqual(tool.values(nodes[7])['dragInMaxEnhance'],'3')
        self.assertEqual(tool.values(nodes[10])['arena'],'false')
        self.assertEqual(tool.values(nodes[10])['shop'],'false')
        self.assertEqual(tool.values(nodes[18])['background'],'loc_detroit')
        self.assertEqual(tool.values(nodes[18])['rankBonus'],'10')
        self.assertEqual(tool.values(nodes[18])['dragin'],'true')
        self.assertEqual(tool.values(nodes[20])['y1'],'-420')
        self.assertEqual(tool.values(nodes[22])['y1'],'-320')
        for identity,limit,band in ((19,10,(4,6)),(20,15,(7,10)),(21,20,(11,15)),(22,25,(16,20))):
            v=tool.values(nodes[identity]);self.assertEqual(v['IsTraining'],'true')
            self.assertEqual(v['dragInMaxEnhance'],str(limit))
            self.assertEqual((v['minlevel'],v['maxlevel']),tuple(map(str,band)))
            self.assertEqual(v['arena'],'false');self.assertEqual(v['dragin'],'true')
            self.assertNotIn('equip',v)

    def test_source_holes_duplicates_and_unapproved_contracts_rejected(self):
        for raw in (self.source.replace(b'id="17"',b'id="18"'),
                    self.source.replace(b'id="17"',b'id="16"'),
                    self.source.replace(b'</towns>',b'<town id="18" name="Contract" /></towns>'),
                    self.source.replace(b'<towns>',b'<!DOCTYPE towns><towns>')):
            with self.assertRaises(ValueError):tool.merge(raw,self.policy)

    def test_unreviewed_locations_and_collision_rejected(self):
        for edit in ('identity','overlap','non_square','bool_level','cap'):
            policy=deepcopy(self.policy);row=policy['locations'][5]
            if edit=='identity':row['id']=23
            elif edit=='overlap':row['bounds']=[175,-346,195,-326]
            elif edit=='non_square':row['bounds']=[-240,-420,-220,-399]
            elif edit=='bool_level':row['levels']=[True,10]
            else:row['max_upgrade']=256
            with self.assertRaises(ValueError):tool.merge(self.source,policy)

    def test_prepared_artifacts_match_exact_sources_and_do_not_touch_shared_files(self):
        report=json.loads((tool.FOLDER/'catalog.json').read_bytes())
        self.assertEqual(report['source_client_sha256'],hashlib.sha256(self.source).hexdigest())
        self.assertEqual(report['source_runtime_sha256'],hashlib.sha256(self.server).hexdigest())
        self.assertEqual((tool.FOLDER/'client/candidate/zones.xml').read_bytes(),tool.merge(self.source,self.policy))
        self.assertEqual((tool.FOLDER/'runtime/evidence/zones_diagnostic.xml').read_bytes(),tool.merge(self.server,self.policy))
        self.assertTrue(report['foreign_rows_preserved_byte_for_byte'])
        with self.assertRaises(ValueError):tool.folder_checked(tool.ROOT)


class OriginalWorldConsumerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0,str(tool.ROOT/'tools'))
        from tools.verify_world_catalog_native import verify
        with tempfile.TemporaryDirectory() as directory:
            cls.proof=verify(tool.FOLDER/'client/candidate/zones.xml',Path(directory)/'proof.json')

    def test_original_loader_populates_all22_native_models(self):
        proof=self.proof;self.assertTrue(proof['passed'])
        self.assertEqual([r['id'] for r in proof['loader_cases']],list(range(1,23)))
        self.assertEqual(proof['loader']['reload_dispatch'],'0x9d1f68')
        self.assertEqual(proof['loader']['loader'],'0x9ea894')
        by_id={r['id']:r for r in proof['loader_cases']}
        self.assertEqual(by_id[7]['bounds'],[315,-410,335,-390])
        self.assertEqual(by_id[20]['bounds'],[-240,-420,-220,-400])
        self.assertEqual(by_id[22]['bounds'],[110,-320,130,-300])
        self.assertEqual((by_id[18]['equipment'],by_id[18]['rank_bonus']),(1,10))
        self.assertEqual((by_id[19]['training'],by_id[19]['max_upgrade']),(1,10))

    def test_original_map_uses_actual_loaded_id_minus_one_and_enabled(self):
        cases=self.proof['town_cases'];self.assertEqual(len(cases),44)
        self.assertEqual({r['town'] for r in cases},set(range(1,23)))
        self.assertTrue(all(r['native_id_lookup'] and r['passed'] for r in cases))
        self.assertTrue(all(r['map_gate_passed']==bool(r['enabled']) for r in cases))

    def test_float_order_reaches_actual_native_tooltip_labels(self):
        mapping=self.proof['float_mapping']
        self.assertEqual(mapping['order'],['influence','experience','profit'])
        self.assertEqual(mapping['sentinel_values'],[1.25,2.5,3.75])
        self.assertEqual(mapping['actual_tooltip_labels'],{'m159':'Influence rate: %s',
            'm219':'Experience rate: %s','m397':'Profit rate: %s'})

    def test_candidate_compressed_zones_packet_uses_original_b9_reader(self):
        shared=self.proof['shared_config'];self.assertTrue(shared['passed'])
        self.assertEqual(shared['name'],'zones')
        self.assertEqual(shared['decompressed_size'],len((tool.FOLDER/'client/candidate/zones.xml').read_bytes()))
        self.assertGreater(shared['original_instruction_parity_count'],20)
        self.assertFalse(self.proof['installed_client_changed'])


if __name__=='__main__':unittest.main()
