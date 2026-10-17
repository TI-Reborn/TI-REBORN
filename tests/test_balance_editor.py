from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from hashlib import sha256
from http.client import HTTPConnection
from io import BytesIO
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
from zipfile import ZipFile

from tools.balance_editor import make_server
from tools.balance_editor_core import Catalog, EditorError, ProfileStore, ROOT, SOURCES, read_json, values
from tio.weapons import WeaponCatalog
from tio.armor import mitigate


class BalanceEditorTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        for path in SOURCES:
            target = self.project/path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT/path).read_bytes())
        self.store = ProfileStore(self.project)
        self.catalog = Catalog(self.store.snapshot())
        self.initial = {p: (self.project/p).read_bytes() for p in SOURCES}

    def profile(self):
        return self.store.create('Баланс оружия')

    def assert_unchanged(self):
        self.assertEqual(self.initial, {p: (self.project/p).read_bytes() for p in SOURCES})

    def test_catalog_is_real_and_special_mechanics_are_read_only(self):
        item = self.catalog.items[304]
        self.assertEqual(item['values']['damage_base'], WeaponCatalog().weapons[304].damage_base)
        self.assertIn('defense', next(i for i in self.catalog.items.values() if i['kind']=='armor')['fields'])
        self.assertEqual(self.catalog.items[2]['fields'], {})
        self.assertNotIn('credits', self.catalog.items[30]['fields'])
        self.assertNotIn('damage_base', self.catalog.items[334]['fields'])
        self.assertNotIn('min_range', self.catalog.items[318]['fields'])
        self.assertNotIn('attack_ap', self.catalog.items[9]['fields'])
        self.assert_unchanged()

    def test_rejects_unknown_or_inapplicable_fields(self):
        for changes in ({'999999': {'weight': 5}}, {'304': {'reload_ap': 1}}, {'304': {'__proto__': {}}},
                        {'2': {'weight': 1}}, {'30': {'credits': 100}}, {'9': {'attack_ap': 1}},
                        {'318': {'damage_base': 1}}, {'0304': {'attack_ap': 3}}, {'../x': {}}):
            with self.subTest(changes=changes), self.assertRaises(EditorError):
                self.catalog.validate(changes)

    def test_rejects_bad_numbers_and_dangling_ammunition(self):
        for value in (-1, True, 1.5, '50', None, 65536):
            with self.subTest(value=value), self.assertRaises(EditorError):
                self.catalog.validate({'304': {'damage_base': value}})
        for changes in ({'304': {'attack_ap': 0}}, {'304': {'min_range': 15}},
                        {'304': {'ammo_id': 9999}}, {'304': {'accuracy': 101}},
                        {'304': {'damage_base': 65535, 'damage_random': 10}}):
            with self.subTest(changes=changes), self.assertRaises(EditorError):
                self.catalog.validate(changes)
        self.assertEqual(self.catalog.validate({'304': {'ammo_id': None}}), {'304': {'ammo_id': None}})

    def test_baseline_values_are_removed_from_diff(self):
        self.assertEqual(self.catalog.validate({'304': {'attack_ap': 5}, '301': {}}), {})

    def test_weapon_export_updates_native_values_and_derived_script(self):
        files = self.catalog.materialize({'304': {'damage_base': 60, 'damage_random': 20, 'attack_ap': 4,
            'ammo_id': 3, 'bullets_count': 2, 'accuracy': 80, 'accuracy_gain_amount': 10, 'damage_fade': 90, 'weight': 100}})
        weapon = read_json(files[SOURCES[0]])['weapons']['304']
        self.assertEqual((weapon['damage_base'], weapon['source_fields']['p_dam']), (60, '60'))
        self.assertEqual((weapon['ammo_id'], weapon['source_fields']['ammo_id']), (3, '3'))
        tree = ET.fromstring(files[SOURCES[1]])
        item = next(n for n in tree if n.get('id')=='304')
        v = values(item)
        self.assertEqual((v['p_dam'],v['actionPoints'],v['damage_fade'],v['damageFade'],v['weight']), ('60','4','90','90','100'))
        script = item.find('for')
        self.assertEqual(script.find("set[@stat='patk']").get('val'), '60')
        self.assertEqual(script.find("add[@stat='patk']").get('val'), '20')
        self.assertEqual(script.find("add[@stat='accuracy']").get('val'), '0.80')
        self.assertEqual(script.find('consume').attrib, {'id':'3','amount':'2'})
        self.assert_unchanged()

    def test_removing_ammo_removes_consumption_without_inventing_reload(self):
        files = self.catalog.materialize({'304': {'ammo_id': None}})
        w = read_json(files[SOURCES[0]])['weapons']['304']
        self.assertNotIn('ammo_id', w['source_fields'])
        self.assertIsNone(w['reload_ap'])
        item = next(n for n in ET.fromstring(files[SOURCES[1]]) if n.get('id')=='304')
        self.assertNotIn('ammo_id', values(item))
        self.assertIsNone(item.find('for/consume'))

    def test_armor_and_price_keep_dependent_representations_consistent(self):
        identity = next(i for i,row in self.catalog.items.items() if row['kind']=='armor' and 'credits' in row['fields'])
        base = self.catalog.items[identity]['base'] if 'base' in self.catalog.items[identity] else self.catalog.items[identity]['values']
        price = base['credits']+100
        files = self.catalog.materialize({str(identity): {'defense': 321, 'credits': price}})
        item = next(n for n in ET.fromstring(files[SOURCES[1]]) if int(n.get('id'))==identity)
        self.assertEqual(values(item)['p_def'], '321')
        if item.find('for') is not None:
            self.assertEqual(item.find("for/add[@stat='pdef']").get('val'), '321')
        pack = self.catalog.prices[identity]['pack_count']
        self.assertEqual(next(r for r in read_json(files[SOURCES[5]])['items'] if r['item_id']==identity)['credits'], price)
        for rows in read_json(files[SOURCES[6]])['item_categories'].values():
            for row in rows:
                if row['item_id']==identity and row['unknown_u32_02']==pack:
                    self.assertEqual(row['unknown_u32_03'],price)
        self.assert_unchanged()

    def test_extension_and_effects_do_not_override_profile(self):
        files = self.catalog.materialize({'5001': {'attack_ap': 6, 'max_range': 12, 'accuracy': 70, 'weight': 25}})
        extension = read_json(files[SOURCES[2]])
        entry = next(i for i in extension['items'] if i['id']==5001)
        self.assertEqual(entry['fields']['actionPoints'], '6')
        self.assertEqual(extension['weapon_catalog_entries']['5001']['attack_ap'],6)
        effect = read_json(files[SOURCES[4]])['items']['5001']
        self.assertEqual((effect['ap'],effect['range'],effect['accuracy']),(6,12,70))
        for xml_path in (SOURCES[1],SOURCES[3]):
            node = next(n for n in ET.fromstring(files[xml_path]) if n.get('id')=='5001')
            self.assertEqual((values(node)['weight'],values(node)['actionPoints']),('25','6'))

    def test_price_changes_do_not_reprice_other_pack_sizes(self):
        docs = dict(self.catalog.documents)
        city = read_json(docs[SOURCES[6]])
        city['item_categories']['0'].append(dict(item_id=304,unknown_u32_02=9,unknown_u32_03=9999))
        docs[SOURCES[6]]=json.dumps(city)
        result=Catalog(docs).materialize({'304':{'credits':1000}})
        rows=read_json(result[SOURCES[6]])['item_categories']['0']
        self.assertEqual(rows[-1]['unknown_u32_03'],9999)

    def test_preview_uses_server_distance_damage_accuracy_and_armor(self):
        preview=self.catalog.preview({'304':{'damage_base':60,'attack_ap':4}},304,defense=100,budget=19)
        baseline=WeaponCatalog()
        for point in preview['series']:
            damage=baseline.distance_damage(304,point['distance'])
            self.assertEqual((point['base']['low'],point['base']['high']),tuple(mitigate(n,100)[0] for n in damage))
            self.assertEqual(point['base']['accuracy'],baseline.accuracy(304,point['distance']))
            self.assertEqual(point['profile']['attacks'],4)
        armor_id=next(i for i,r in self.catalog.items.items() if r['kind']=='armor')
        preview=self.catalog.preview({str(armor_id):{'defense':100}},armor_id)
        self.assertEqual(preview['armor'][2]['profile'],50)
        self.assert_unchanged()

    def test_blast_preview_does_not_apply_direct_fire_distance_falloff(self):
        preview=self.catalog.preview({'317':{'damage_base':80}},317)
        in_range=[p for p in preview['series'] if p['profile']['in_range']]
        self.assertTrue(in_range)
        self.assertEqual({p['profile']['low'] for p in in_range},{80})
        self.assertEqual(self.catalog.preview({},321)['kind'],'special')
        self.assertEqual(self.catalog.preview({},318)['kind'],'special')

    def test_profile_roundtrip_preserves_original_files_and_snapshots(self):
        p=self.profile()
        saved=self.store.save(p['id'],1,p['name'],{'304':{'damage_base':60}})
        self.assertEqual(saved['revision'],2)
        self.assertEqual(self.store.load(p['id'])['changes'],{'304':{'damage_base':60}})
        imported=self.store.create('Копия',imported=saved)
        self.assertNotEqual(imported['id'],saved['id'])
        self.assertEqual(imported['changes'],saved['changes'])
        self.assertEqual(len(self.store.list()),2)
        self.assert_unchanged()

    def test_simultaneous_save_has_exactly_one_winner(self):
        p=self.profile()
        def save(value):
            try:
                self.store.save(p['id'],1,p['name'],{'304':{'damage_base':value}})
                return 200
            except EditorError as exc:
                return exc.status
        with ThreadPoolExecutor(2) as pool:
            self.assertEqual(sorted(pool.map(save,[60,70])),[200,409])
        self.assertEqual(self.store.load(p['id'])['revision'],2)

    def test_changed_baseline_blocks_save_export_and_import(self):
        p=self.profile()
        target=self.project/SOURCES[0]
        target.write_bytes(target.read_bytes()+b'\n')
        self.assertEqual(self.store.stale(p),[SOURCES[0]])
        for operation in (lambda:self.store.save(p['id'],1,p['name'],{}),
                          lambda:self.store.export(p['id']),lambda:self.store.create('Импорт',p)):
            with self.assertRaises(EditorError) as exc:
                operation()
            self.assertEqual(exc.exception.status,409)

    def test_atomic_write_failure_keeps_previous_revision(self):
        p=self.profile()
        with patch('tools.balance_editor_core.os.replace',side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):self.store.save(p['id'],1,p['name'],{'304':{'damage_base':60}})
        self.assertEqual(self.store.load(p['id'])['revision'],1)
        self.assertEqual(list(self.store.directory.glob('*.tmp')),[])

    def test_profile_path_traversal_and_tampered_snapshot_are_rejected(self):
        for identity in ('../weapon_catalog','C:\\Windows','a'*33,'A'*32,''):
            with self.assertRaises(EditorError):self.store.path(identity)
        p=self.profile();p['documents'][SOURCES[0]]+=' '
        with self.assertRaises(EditorError):self.store.create('Повреждённый',p)
        p=self.profile();p['documents']['../../outside']='bad'
        with self.assertRaises(EditorError):self.store.create('Путь',p)

    def test_export_is_review_only_and_candidate_hashes_match(self):
        p=self.profile();p=self.store.save(p['id'],1,p['name'],{'304':{'attack_ap':4}})
        raw=self.store.export(p['id'])
        with ZipFile(BytesIO(raw)) as z:
            names=set(z.namelist())
            self.assertEqual(names,{'profile.json','changes.json','manifest.json','README.ru.txt',*('candidate/'+p for p in SOURCES)})
            manifest=json.loads(z.read('manifest.json'))
            self.assertFalse(manifest['deployment_performed'])
            self.assertFalse(manifest['database_included'])
            for row in manifest['files']:
                self.assertEqual(sha256(z.read('candidate/'+row['path'])).hexdigest(),row['sha256'])
            self.assertEqual(json.loads(z.read('changes.json'))[0]['after'],4)
            weapon_file=self.project/'candidate-weapons.json'
            weapon_file.write_bytes(z.read('candidate/config/weapon_catalog.json'))
            self.assertEqual(WeaponCatalog(weapon_file).weapons[304].attack_ap,4)
        self.assert_unchanged()

    def test_unchanged_materialization_preserves_all_source_bytes(self):
        self.assertEqual({p:s.encode('utf-8') for p,s in self.catalog.materialize({}).items()},self.initial)

    def test_duplicate_json_keys_and_nonfinite_numbers_are_rejected(self):
        for raw in ('{"304":1,"304":2}','{"x":NaN}','{"x":Infinity}'):
            with self.assertRaises(EditorError):read_json(raw)

    def test_http_editor_workflow_and_cross_origin_protection(self):
        server=make_server(self.store,0)
        thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        port=server.server_address[1]
        def request(method,path,body=None,token=None,origin=None,host=None):
            connection=HTTPConnection('127.0.0.1',port,timeout=5)
            headers={}
            if token:headers['X-Editor-Token']=token
            if origin:headers['Origin']=origin
            if host:headers['Host']=host
            if body is not None:headers['Content-Type']='application/json'
            connection.request(method,path,body=json.dumps(body) if body is not None else None,headers=headers)
            response=connection.getresponse();status=response.status;raw=response.read();connection.close()
            return status,raw
        status,html=request('GET','/')
        self.assertEqual(status,200)
        token=re.search(b'name="editor-token" content="([^"]+)"',html)[1].decode()
        self.assertEqual(request('POST','/api/profiles',{'name':'bad'})[0],403)
        self.assertEqual(request('POST','/api/profiles',{'name':'bad'},token,origin='https://evil.example')[0],403)
        self.assertEqual(request('GET','/',host='evil.example')[0],403)
        self.assertEqual(request('GET','/../config/server.toml')[0],404)
        status,raw=request('POST','/api/profiles',{'name':'HTTP профиль'},token)
        self.assertEqual(status,201);p=json.loads(raw)['profile']
        status,raw=request('POST','/api/profiles/'+p['id'],{'revision':1,'name':p['name'],'changes':{'304':{'attack_ap':4}}},token)
        self.assertEqual(status,200);self.assertEqual(json.loads(raw)['profile']['revision'],2)
        self.assertEqual(request('GET','/api/profiles/'+p['id']+'/candidate',token=token)[0],200)
        self.assert_unchanged()


if __name__=='__main__':
    unittest.main()
