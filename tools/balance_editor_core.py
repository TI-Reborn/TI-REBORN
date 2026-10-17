"""Isolated balance profiles. No game database or live catalog writes."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile, TemporaryDirectory
from threading import RLock
import uuid
import xml.etree.ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
SOURCES = (
    'config/weapon_catalog.json', 'evidence/items_diagnostic.xml',
    'config/battle_item_catalog_extension.json', 'config/battle_item_catalog_extension.xml',
    'config/battle_item_effects.json', 'config/credit_economy.json',
    'config/city_catalogs.json', 'config/sc_catalog.json',
)
WEAPON_FIELDS = {
    'damage_base': ('p_dam', 0, 65535), 'damage_random': ('rnd_dam', 0, 65535),
    'attack_ap': ('actionPoints', 1, 255), 'min_range': ('minRange', 0, 64),
    'max_range': ('maxRange', 0, 64), 'bullets_count': ('bulletsCount', 1, 255),
    'ammo_id': ('ammo_id', 0, 65535),
}
SOURCE_FIELDS = {
    'accuracy': (0, 100), 'accuracy_gain_amount': (0, 100), 'damage_fade': (0, 100),
    'critical': (0, 100),
}
LABELS = {
    'damage_base': 'Базовый урон', 'damage_random': 'Добавочный урон',
    'attack_ap': 'ОД на атаку', 'min_range': 'Минимальная дальность',
    'max_range': 'Максимальная дальность', 'bullets_count': 'Патронов за атаку',
    'ammo_id': 'Боеприпас', 'accuracy': 'Точность, %',
    'accuracy_gain_amount': 'Прибавка точности вблизи, %', 'damage_fade': 'Остаток урона вдали, %',
    'critical': 'Критический шанс, %', 'defense': 'Защита', 'weight': 'Вес',
    'credits': 'Цена упаковки, кредиты',
}


class EditorError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def dumps(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n'


def read_json(raw):
    def pairs(rows):
        result = {}
        for k, v in rows:
            if k in result:
                raise EditorError('Повторяющийся ключ JSON: ' + k)
            result[k] = v
        return result
    try:
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(EditorError('Недопустимое число JSON')))
    except (ValueError, TypeError) as exc:
        raise EditorError('Некорректный JSON: ' + str(exc)) from exc


def now():
    return datetime.now(timezone.utc).isoformat()


def values(node):
    return {v.get('key'): v.get('val') for v in node.findall('value')}


def set_value(node, key, value):
    old = next((v for v in node.findall('value') if v.get('key') == key), None)
    if value is None:
        if old is not None:
            node.remove(old)
    else:
        if old is None:
            old = ET.SubElement(node, 'value', key=key)
        old.set('val', str(value))


class Catalog:
    def __init__(self, documents):
        if set(documents) != set(SOURCES) or any(not isinstance(x, str) for x in documents.values()):
            raise EditorError('Неполный набор исходных каталогов')
        self.documents = documents
        self.weapon = read_json(documents[SOURCES[0]])
        self.xml = ET.fromstring(documents[SOURCES[1]])
        self.effects = read_json(documents[SOURCES[4]])['items']
        self.prices = {r['item_id']: r for r in read_json(documents[SOURCES[5]])['items']}
        self.items = {}
        for node in self.xml:
            identity = int(node.get('id'))
            if identity in self.items:
                raise EditorError('Повторяющийся ID предмета')
            source = values(node)
            weapon = self.weapon['weapons'].get(str(identity))
            kind = ('weapon' if weapon else 'armor' if source.get('itype') == 'armor'
                    else 'ammo' if str(identity) in self.weapon['ammunition']
                    else 'medical' if source.get('itype') == 'medkit' else 'other')
            data = {'weight': int(source.get('weight', 0))}
            schema = {'weight': {'min': 0, 'max': 65535}}
            notes = []
            if weapon:
                for field, (_, low, high) in WEAPON_FIELDS.items():
                    data[field] = weapon[field]
                    schema[field] = {'min': low, 'max': high, 'nullable': field == 'ammo_id'}
                for field, (low, high) in SOURCE_FIELDS.items():
                    if field in weapon['source_fields']:
                        data[field] = int(weapon['source_fields'][field])
                        schema[field] = {'min': low, 'max': high}
                # These items have separate authoritative rules in code or combat_rules.json.
                if identity in (316, 317, 340):
                    notes.append('Разброс и радиус закреплены отдельными правилами; здесь не редактируются.')
                if identity == 334:
                    for field in list(schema):
                        if field != 'weight':
                            schema.pop(field)
                    notes.append('Урон и ОД жилета смертника определяются отдельной механикой.')
                elif str(identity) in self.effects:
                    for field in list(schema):
                        if field not in ('weight', 'attack_ap', 'max_range', 'accuracy', 'accuracy_gain_amount'):
                            schema.pop(field)
                    notes.append('Спецэффект: урон, минимальная дальность и боеприпасы здесь только для просмотра.')
                if identity in (321, 325):
                    schema = {k: v for k, v in schema.items() if k == 'weight'}
                    notes.append('Мина: урон и стоимость установки задаются отдельной серверной политикой.')
                if identity in (316, 317, 319, 323, 340):
                    schema.pop('damage_fade', None)
                    schema.pop('critical', None)
                    notes.append('Взрыв: урон не снижается от дальности броска; критические попадания не применяются.')
                if identity in (317, 319, 323, 340):
                    schema.pop('ammo_id', None)
                    if identity != 323:
                        schema.pop('bullets_count', None)
                    notes.append('Тип расходуемого боеприпаса закреплён механикой этого оружия.')
            if kind == 'armor':
                data['defense'] = int(source.get('p_def', 0))
                schema['defense'] = {'min': 0, 'max': 65535}
            if identity in self.prices:
                data['credits'] = self.prices[identity]['credits']
                if identity != 30:
                    schema['credits'] = {'min': 1, 'max': 1000000000}
                else:
                    notes.append('Цена Upgrade Kit закреплена проверкой серверной экономики.')
            if kind == 'medical':
                notes.append('Лечение и ОД расходников могут задаваться кодом; в этой версии доступны вес и цена.')
            if kind == 'weapon':
                notes.append('Магазины и перезарядка не реализованы: патроны — расход за одну атаку.')
            if identity in (0, 1, 2) or identity >= 65500:
                schema = {}
                notes.append('Служебный предмет: только просмотр.')
            self.items[identity] = {
                'id': identity, 'name': node.get('name', str(identity)), 'kind': kind,
                'weapon_type': weapon['weapon_type'] if weapon else '',
                'values': data, 'fields': schema, 'notes': notes,
                'pack_count': self.prices.get(identity, {}).get('pack_count'),
            }
        # Some synthetic NPC weapons have no client XML row; show them read-only.
        for identity, weapon in self.weapon['weapons'].items():
            if int(identity) not in self.items:
                self.items[int(identity)] = {'id': int(identity), 'name': weapon['name'], 'kind': 'weapon',
                    'weapon_type': weapon['weapon_type'], 'values': {k: weapon[k] for k in WEAPON_FIELDS},
                    'fields': {}, 'notes': ['Серверный шаблон без XML предмета: только просмотр.'], 'pack_count': None}

    def validate(self, changes):
        if not isinstance(changes, dict) or len(changes) > len(self.items):
            raise EditorError('Некорректный набор изменений')
        clean = {}
        for key, patch in changes.items():
            if not isinstance(key, str) or not key.isascii() or not key.isdecimal() or str(int(key)) != key:
                raise EditorError('Некорректный ID предмета')
            item = self.items.get(int(key))
            if item is None or not isinstance(patch, dict):
                raise EditorError('Неизвестный предмет или некорректные поля')
            merged = dict(item['values'])
            for field, value in patch.items():
                rule = item['fields'].get(field)
                if rule is None:
                    raise EditorError(f"{item['name']}: поле {field} недоступно для изменения")
                if not (value is None and rule.get('nullable')):
                    if type(value) is not int or not rule['min'] <= value <= rule['max']:
                        raise EditorError(f"{item['name']}: {LABELS[field]} — целое число от {rule['min']} до {rule['max']}")
                merged[field] = value
            if 'min_range' in merged and merged['min_range'] > merged['max_range']:
                raise EditorError(f"{item['name']}: минимальная дальность больше максимальной")
            if merged.get('damage_base', 0) + merged.get('damage_random', 0) > 65535:
                raise EditorError(f"{item['name']}: суммарный базовый урон превышает 65535")
            if merged.get('ammo_id') is not None and str(merged['ammo_id']) not in self.weapon['ammunition']:
                raise EditorError(f"{item['name']}: неизвестный боеприпас")
            filtered = {k: v for k, v in patch.items() if v != item['values'][k]}
            if filtered:
                clean[key] = filtered
        return clean

    def rows(self, changes):
        rows = []
        for identity in sorted(self.items):
            row = deepcopy(self.items[identity])
            row['base'] = dict(row['values'])
            row['values'].update(changes.get(str(identity), {}))
            row['changed'] = sorted(changes.get(str(identity), {}))
            rows.append(row)
        return rows

    def materialize(self, changes):
        changes = self.validate(changes)
        data = {p: read_json(s) for p, s in self.documents.items() if p.endswith('.json')}
        xml = {p: ET.fromstring(s) for p, s in self.documents.items() if p.endswith('.xml')}
        weapons = data[SOURCES[0]]
        extension = data[SOURCES[2]]
        effects = data[SOURCES[4]]['items']
        for key, patch in changes.items():
            identity = int(key)
            weapon = weapons['weapons'].get(key)
            native = {}
            for field, value in patch.items():
                if field in WEAPON_FIELDS:
                    weapon[field] = value
                    native[WEAPON_FIELDS[field][0]] = value
                elif field in SOURCE_FIELDS:
                    native[field] = value
                elif field == 'weight':
                    native['weight'] = value
                elif field == 'defense':
                    native['p_def'] = value
            if weapon:
                for field, value in native.items():
                    if value is None:
                        weapon['source_fields'].pop(field, None)
                    else:
                        weapon['source_fields'][field] = str(value)
                if key in extension.get('weapon_catalog_entries', {}):
                    extension['weapon_catalog_entries'][key] = deepcopy(weapon)
            if key in weapons['ammunition']:
                for field, value in native.items():
                    if value is not None:
                        weapons['ammunition'][key]['source_fields'][field] = str(value)
            for row in extension['items']:
                if row['id'] == identity:
                    row['fields'].update({k: str(v) for k, v in native.items() if v is not None})
                    if native.get('ammo_id', 0) is None:
                        row['fields'].pop('ammo_id', None)
            if key in extension.get('amendments', {}):
                extension['amendments'][key].update({k: str(v) for k, v in native.items() if v is not None})
            if key in effects:
                for field, target in [('attack_ap', 'ap'), ('max_range', 'range'),
                                      ('accuracy', 'accuracy'), ('damage_base', 'damage_base'), ('damage_random', 'damage_random')]:
                    if field in patch and target in effects[key]:
                        effects[key][target] = patch[field]
            for tree in xml.values():
                node = next((n for n in tree if n.get('id') == key), None)
                if node is None:
                    continue
                for field, value in native.items():
                    set_value(node, field, value)
                # Alias values are separately consumed by native clients.
                if 'damage_fade' in native:
                    set_value(node, 'damageFade', native['damage_fade'])
                script = node.find('for')
                if script is not None:
                    derived = {('set', 'patk'): native.get('p_dam'), ('add', 'patk'): native.get('rnd_dam'),
                               ('add', 'pdef'): native.get('p_def'),
                               ('add', 'accuracy'): None if 'accuracy' not in native else f"{native['accuracy']/100:.2f}",
                               ('add', 'accuracyGain'): None if 'accuracy_gain_amount' not in native else f"{native['accuracy_gain_amount']/100:.2f}"}
                    for (tag, stat), value in derived.items():
                        if value is None:
                            continue
                        part = next((n for n in script if n.tag == tag and n.get('stat') == stat), None)
                        if part is None:
                            part = ET.SubElement(script, tag, stat=stat)
                        part.set('val', str(value))
                    if 'ammo_id' in patch or 'bullets_count' in patch:
                        for part in list(script.findall('consume')):
                            script.remove(part)
                        if weapon['ammo_id'] is not None:
                            ET.SubElement(script, 'consume', id=str(weapon['ammo_id']), amount=str(weapon['bullets_count']))
            if 'credits' in patch:
                price = patch['credits']
                pack = self.prices[identity]['pack_count']
                next(r for r in data[SOURCES[5]]['items'] if r['item_id'] == identity)['credits'] = price
                city = data[SOURCES[6]]
                for offers in city['item_categories'].values():
                    for row in offers:
                        if row['item_id'] == identity and row['unknown_u32_02'] == pack:
                            row['unknown_u32_03'] = price
                for row in city['premium_items']:
                    if row['item_id'] == identity and row['pack_count'] == pack:
                        row['gold'] = price  # Historical wire field carries credits.
                for row in data[SOURCES[7]]['offers']:
                    if row['item_id'] == identity and row['pack_count'] == pack:
                        row['credits'] = price
        result = dict(self.documents)
        for path, value in data.items():
            if value != read_json(self.documents[path]):
                result[path] = dumps(value)
        for path, tree in xml.items():
            # Preserve original XML bytes when no semantic changes occurred.
            if ET.tostring(tree) != ET.tostring(ET.fromstring(self.documents[path])):
                ET.indent(tree)
                result[path] = ET.tostring(tree, encoding='utf-8', xml_declaration=True).decode('utf-8') + '\n'
        return result

    def preview(self, changes, identity, defense=0, budget=20):
        if type(identity) is not int or identity not in self.items:
            raise EditorError('Неизвестный предмет')
        if type(defense) is not int or not 0 <= defense <= 65535 or type(budget) is not int or not 1 <= budget <= 255:
            raise EditorError('Некорректная защита или запас ОД')
        changes = self.validate(changes)
        from tio.weapons import WeaponCatalog
        from tio.armor import mitigate
        from tio.weapon_effects import BLAST
        if str(identity) in self.effects or identity in (321, 325):
            return {'kind': 'special', 'series': [], 'note': 'Этот предмет использует отдельную механику. График обычной атаки к нему неприменим.'}
        if str(identity) not in self.weapon['weapons']:
            row = self.items[identity]
            before = row['values'].get('defense', 0)
            after = changes.get(str(identity), {}).get('defense', before)
            return {'kind': row['kind'], 'armor': [{'raw': n, 'base': mitigate(n, before)[0], 'profile': mitigate(n, after)[0]} for n in (20, 50, 100, 200)], 'series': []}
        with TemporaryDirectory(prefix='tio-balance-preview-') as folder:
            path = Path(folder)/'weapon_catalog.json'
            path.write_text(self.documents[SOURCES[0]], encoding='utf-8')
            base = WeaponCatalog(path)
            path.write_text(self.materialize(changes)[SOURCES[0]], encoding='utf-8')
            proposed = WeaponCatalog(path)
        series = []
        maximum = min(64, max(base.weapons[identity].max_range, proposed.weapons[identity].max_range, 10))
        for distance in range(1, maximum + 1):
            point = {'distance': distance}
            for key, catalog in [('base', base), ('profile', proposed)]:
                weapon = catalog.weapons[identity]
                low, high = ((weapon.damage_base, weapon.damage_base + weapon.damage_random)
                             if identity in BLAST else catalog.distance_damage(identity, distance))
                low, high = mitigate(low, defense)[0], mitigate(high, defense)[0]
                accuracy = catalog.accuracy(identity, distance)
                point[key] = {'low': low, 'high': high, 'accuracy': accuracy,
                    'damage_per_ap': round((low+high)/2/weapon.attack_ap, 2),
                    'attacks': budget//weapon.attack_ap,
                    'in_range': weapon.min_range <= distance <= weapon.max_range}
            series.append(point)
        return {'kind': 'weapon', 'series': series, 'defense': defense, 'budget': budget,
            'note': 'Диапазон успешной атаки после брони. Для очереди — вся очередь при попадании всех пуль. Промахи, навыки, критические эффекты, горение и укрытия не учтены; это не симуляция боя.'}


class ProfileStore:
    def __init__(self, project=ROOT, directory=None):
        self.project = Path(project)
        self.directory = Path(directory) if directory else self.project/'data/balance-editor/profiles'
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()

    def snapshot(self):
        return {p: (self.project/p).read_bytes().decode('utf-8') for p in SOURCES}

    @staticmethod
    def title(name):
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80 or any(ord(c) < 32 for c in name):
            raise EditorError('Название профиля: от 1 до 80 символов')
        return name.strip()

    def path(self, identity):
        if not isinstance(identity, str) or not re.fullmatch(r'[0-9a-f]{32}', identity):
            raise EditorError('Некорректный ID профиля')
        path = self.directory/(identity+'.json')
        if path.is_symlink():
            raise EditorError('Символические ссылки профилей не поддерживаются')
        return path

    def _write(self, profile):
        path = self.path(profile['id'])
        temp = None
        try:
            with NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.directory, prefix='.profile-', suffix='.tmp', delete=False) as f:
                temp = Path(f.name)
                f.write(dumps(profile)); f.flush(); os.fsync(f.fileno())
            os.replace(temp, path)
        finally:
            if temp is not None and temp.exists():
                temp.unlink()

    def load(self, identity):
        try:
            profile = read_json(self.path(identity).read_text(encoding='utf-8'))
        except FileNotFoundError as exc:
            raise EditorError('Профиль не найден', 404) from exc
        self._validate_profile(profile)
        if profile['id'] != identity:
            raise EditorError('ID файла и профиля различаются')
        return profile

    def _validate_profile(self, profile):
        if not isinstance(profile, dict) or profile.get('schema') != 1 or profile.get('purpose') != 'isolated-balance-profile':
            raise EditorError('Неподдерживаемый формат профиля')
        self.title(profile.get('name'))
        if type(profile.get('revision')) is not int or profile['revision'] < 1:
            raise EditorError('Некорректная ревизия')
        documents = profile.get('documents', {})
        if not isinstance(documents, dict) or set(documents) != set(SOURCES) or any(not isinstance(v, str) for v in documents.values()):
            raise EditorError('Неполный снимок каталогов')
        if profile.get('baseline') != {p: sha256(v.encode('utf-8')).hexdigest() for p, v in documents.items()}:
            raise EditorError('Снимок каталогов повреждён')
        Catalog(documents).validate(profile.get('changes'))

    def list(self):
        result = []
        for path in sorted(self.directory.glob('*.json')):
            try:
                p = self.load(path.stem)
                result.append({k: p[k] for k in ('id', 'name', 'revision', 'updated_at')})
            except (ValueError, OSError, ET.ParseError):
                continue
        return sorted(result, key=lambda p: p['updated_at'], reverse=True)

    def create(self, name, imported=None):
        with self.lock:
            documents = self.snapshot()
            changes = {}
            if imported is not None:
                self._validate_profile(imported)
                if imported['baseline'] != {p: sha256(v.encode('utf-8')).hexdigest() for p, v in documents.items()}:
                    raise EditorError('Каталоги импортированного профиля отличаются от текущих. Требуется ручное согласование.', 409)
                changes = Catalog(documents).validate(imported['changes'])
            profile = dict(schema=1, purpose='isolated-balance-profile', id=uuid.uuid4().hex,
                name=self.title(name), revision=1, created_at=now(), updated_at=now(),
                baseline={p: sha256(v.encode('utf-8')).hexdigest() for p, v in documents.items()},
                documents=documents, changes=changes)
            self._write(profile)
            return profile

    def stale(self, profile):
        return [p for p, expected in profile['baseline'].items()
                if not (self.project/p).is_file() or sha256((self.project/p).read_bytes()).hexdigest() != expected]

    def save(self, identity, revision, name, changes):
        with self.lock:
            profile = self.load(identity)
            if type(revision) is not int or revision != profile['revision']:
                raise EditorError('Профиль изменён в другом окне. Сначала загрузите актуальную версию.', 409)
            if self.stale(profile):
                raise EditorError('Исходные каталоги изменились. Создайте профиль на новой основе.', 409)
            profile['name'] = self.title(name)
            profile['changes'] = Catalog(profile['documents']).validate(changes)
            profile['revision'] += 1
            profile['updated_at'] = now()
            self._write(profile)
            return profile

    def state(self, profile=None):
        documents = profile['documents'] if profile else self.snapshot()
        catalog = Catalog(documents)
        changes = profile['changes'] if profile else {}
        return dict(profile=None if profile is None else {k: v for k, v in profile.items() if k != 'documents'},
            items=catalog.rows(changes), profiles=self.list(), labels=LABELS,
            ammunition=[{'id': int(k), 'name': v['name']} for k, v in catalog.weapon['ammunition'].items()],
            stale_sources=self.stale(profile) if profile else [],
            mode='isolated', source='local-project', project=str(self.project))

    def export(self, identity):
        with self.lock:
            profile = self.load(identity)
            if self.stale(profile):
                raise EditorError('Исходные каталоги изменились. Экспорт кандидата остановлен.', 409)
            catalog = Catalog(profile['documents'])
            candidate = catalog.materialize(profile['changes'])
            diffs = []
            for key, patch in profile['changes'].items():
                for field, value in patch.items():
                    diffs.append(dict(item_id=int(key), name=catalog.items[int(key)]['name'], field=field,
                                      before=catalog.items[int(key)]['values'][field], after=value))
            manifest = dict(schema=1, purpose='review-only-balance-candidate', profile=profile['name'],
                revision=profile['revision'], created_at=now(), baseline=profile['baseline'],
                deployment_performed=False, database_included=False,
                files=[dict(path=p, sha256=sha256(s.encode('utf-8')).hexdigest(),
                            changed=s != profile['documents'][p]) for p, s in candidate.items()])
            result = BytesIO()
            with ZipFile(result, 'w', ZIP_DEFLATED) as z:
                z.writestr('profile.json', dumps(profile))
                z.writestr('changes.json', dumps(diffs))
                z.writestr('manifest.json', dumps(manifest))
                z.writestr('README.ru.txt', 'Кандидат баланса для проверки, не автоматическое обновление.\n'
                    'Основа: локальные каталоги, не снимок хостинга. Не копируйте архив поверх сервера.\n'
                    'Перед применением: сверить актуальный хостинг, согласовать правила/цены, подготовить клиентский items.xml,\n'
                    'резервные копии и проверить общий бой двумя реальными аккаунтами.\n'
                    'Изменения цены относятся к исходному размеру упаковки. Другие размеры предложений не пересчитываются.\n'
                    'evidence/items_diagnostic.xml является серверной диагностической базой; публикация клиентского XML — отдельный шаг.\n')
                for path, content in candidate.items():
                    z.writestr('candidate/'+path, content)
            return result.getvalue()
