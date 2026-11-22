# Предметные эффекты боя: пакет для интеграции

Пакет реализует авторитетные предметные эффекты: инвентарь, ОД, HP, прокачка, эффекты, RNG и база меняются одной транзакцией. Основные подключения выполнены в общем боевом сервисе; ниже сохранён контракт интеграции. Новый клиентский адаптер собран только поверх опубликованной phase2 DLL. Автоматические проверки исполняют оригинальный код клиента, но проверка пикселей полного Windows GUI и игра двумя hosted клиентами остаются отдельным этапом.

## Каталог и политика

`config/battle_item_effects.json` содержит числа из руководства (печатные страницы 40, 63–64, 79–82) и явно помеченные решения эмулятора там, где источник не определяет механику. Smoke 318 использует параметры установленного CFG; срок 3 хода владельца и непрозрачный диск являются политикой эмулятора. ПНВ уменьшает штраф темноты: штатный обзор −3, активный прибор +2. Уровень, сроки и бонусы бустеров взяты из руководства.

`tools/build_battle_item_extension.py` воспроизводимо генерирует `config/battle_item_catalog_extension.xml` и `.json`. IDs 5001–5011 проверены на отсутствие в установленном `base/items.cfg` и `evidence/items_diagnostic.xml`. Это новые IDs эмулятора, без утверждения об историческом соответствии. Flare 5001 клонирует поддержанный Grenade 317. ПНВ 5002 и бустеры 5003–5011 клонируют поддержанный medkit 33 и его native33 formatter. Все перечисленные изображения уже существуют в установленном клиенте. Booster prices выражены в Gold; покупка использует обычную транзакцию кошелька после добавления каталога root.

При интеграции объединить XML с опубликованным `base/shared config/items.xml`, `weapon_catalog_entries` с серверным WeaponCatalog и применить `amendments` к 24 и 35. Runtime XML loader использует исходные поля поддержанных классов; установленный `items.cfg` служит историческим источником импорта и проверки коллизий, его обновление не требуется. Smoke/Flash имеют нулевой HP damage: каталог обычных гранат не должен перехватывать их раньше item effects.

## Начало боя, обзор и броня

```python
from tio import battle_item_effects as item_effects
item_effects.initialize(combat)  # -> dict primitive state; safe idempotent
field.item_darkness = True       # only authoritative mines/dark locations
item_effects.refresh_sight(combat)  # -> tuple[bytes] native4E attribute12
```

Флаг темноты выставляется по серверной карте/типу сцены, не по клиентскому сообщению. Обычные арены по умолчанию светлые. `refresh_sight` надо вызывать до projection после kill/equip/passive изменения радиуса: он сохраняет стороннюю прибавку в `base_sight`, даже если в это время действует Flash. Рабочий радиус помещается в `BattleActor.sight_radius`; базовый PetInfo остаётся постоянным.

В `visibility.visible_actors(field, owner)` перед обычной логикой:

```python
if getattr(field, 'combat', None) is not None:
    return item_effects.visible_actors(field.combat, owner, field=field)
```

Параметр `field=field` обязателен: движение пересчитывает видимость на копии поля с промежуточными координатами. `can_observe(combat, observer, target, field=None) -> bool` включает обычный обзор, освещённые клетки в нормальном радиусе наблюдателя и разведку союзной стороны. Обычная геометрия, двери и smoke проверяются для каждой линии. `clear_item_sight(combat, start, end) -> bool` проверяет только динамический дым; добавить его к обычной проверке direct-fire LOS, а не использовать вместо статической геометрии. Для непрямых гранат дым не препятствует броску.

`armor_bonus(combat, actor_id) -> int` возвращает 20 для живого бойца с активным ПНВ, иначе 0. Прибавить его в `Combat.defense` и `displayed_armor`; после use/begin/end сравнить armor до/после и послать `armor_display.encode_armor(id, total)` (native4E attribute9). ПНВ является прибором в инвентаре, поэтому clone-medkit не даёт пассивной armor сам по себе. `durability.durable/repair` должны разрешать ID 5002, хотя его formatter class — medkit. Работа бинокля расходует 5 прочности, ПНВ 3.

## Native действия и ответы

Все функции возвращают `tuple[bytes]` в обычной структуре сервиса. Ошибки валидации — `ValueError`, до какого-либо частичного результата. Вызов находится внутри общей battle journal transaction. Нельзя отдавать tuple напрямую всем участникам: обычный `project_action` фильтрует private30, изменения атрибутов скрытых врагов и 4B hit list по видимости получателя.

```python
result = item_effects.attack(combat, owner, request49, view=view)
if result is not None:
    return result
# otherwise ordinary Combat.attack
```

`attack(combat, owner, AttackRequest, *, view=None) -> tuple[bytes] | None` обрабатывает экипированные Smoke 318, Flash 320, Flare 5001 и Suicide Jacket 334 в armor slot4. `None` означает обычное оружие. Ответ начинается native4B с requested target и отдельным настоящим RNG impact, затем AP4E, private inventory30 и нужные sight4E12. Flash hits имеют damage=0 и исходный HP; применяются ко всем сторонам в radius3 за исключением целей за препятствием. Smoke/Flare создают shared primitive areas. Самоподрыв всегда центрируется на бойце, использует существующий death/loot/armor pipeline, отнимает все собственные HP. По руководству (стр.64) жилет несовместим с любым оружием в руках: `tio.equipment.require_no_suicide_jacket_weapon` отвергает надевание жилета при оружии в слоте16 или128, оружие в любую руку при надетом жилете и смену рук6D (город, пакетная и прямая экипировка в бою). Снятие предметов не запрещается, поэтому старые сохранения с обоими предметами можно исправить. Throwing обучается один раз за расход предмета, в wager не меняется.

```python
if item_effects.handles_use(selected.template_id):
    return item_effects.use(combat, owner, request33)
```

`handles_use(template_id) -> bool`; `use(combat, owner, ItemAction, *, now=None) -> tuple[bytes]` обрабатывают Champagne 33, Vision35, Binocular24, ПНВ5002 и бустеры5003–5011. Требуется option255: явный target-mask является экипировкой, не Use. Этот маршрут должен стоять до общего `Combat.equip/use_medkit`. Champagne лечит до24 HP за2 ОД; полное HP отвергается без расхода. Vision даёт +1 обзор за10 ОД на10 ходов бойца с cooldown15. ПНВ toggle без повторной оплаты на текущем поколении хода; новый ход автоматически снимает 3 ОД и прочность, при нехватке отключает прибор. Последнее оплаченное применение действует до завершения текущего хода, даже если прибор разрушился.

Бинокль: `use` выбирает проверенный instance24 в `recon_selection` без расхода ОД, затем `recon_target(combat, owner, AttackRequest) -> tuple[bytes]` расходует 5 ОД/прочности и создаёт союзный disk radius5 до конца хода. Маршрут второго native49 разрешать только при выбранном instance; после успешного действия выбор удаляется, после конца хода очищается. `deploy/client_battle_items.py` дополняет оригинальное двойное нажатие инвентаря `a4dba0→a6516c→9903a4→33`: после выбора 24 включает targeting state11 эмулятора и штатный binocular cursor14; map click отправляет штатный49. Повторные, чужие, умершие, отменённые и выходящие за карту цели не отправляются. Состояние11 является явно новым расширением.

Проверка полного HP обходится только для Vision35 и новых medkit-clones5002–5011, после чего выполняется оригинальное сравнение ОД. Champagne33 сохраняет отказ при полном HP. Бустеры имеют metadata AP0, включая активацию через городской инвентарь. Клиентский AP gate ПНВ5002 остаётся3, поэтому штатный GUI требует3 ОД и для выключения, хотя серверное выключение бесплатно. Это ограничение интерфейса, которое надо учитывать при клиентском QA.

## Проекция длительных областей

`tio.battle_item_visuals.packets(field, owner) -> tuple[bytes]` возвращает полный F7/v1 snapshot видимых клеток дыма, освещения и разведки, включая пустой snapshot для очистки. Подключить его к `VisibilityView.refresh`, initial battle и reconnect после расчёта item-aware visibility. Содержимое каждой клетки — только x/y/kind; IDs владельцев, скрытые центры, inventory instances и чужая разведка не передаются. Клиент не вычисляет TTL: сервер присылает актуальное состояние после смены хода, движения и действий.

Видимость поверхности дыма использует статическую LOS и радиус союзного живого наблюдателя. Сам дым блокирует боевой обзор, но не скрывает свою видимую поверхность. Перекрытие дыма и света отображается дымом. Flare в темноте показывает освещённые клетки только в нормальном радиусе; разведка отображается только союзной стороне и прекращается после смерти источника. Лимит4096 клеток детерминированно оставляет ближайшие, затем y/x; он ограничивает картинку, не игровую механику.

F7 является явным расширением эмулятора. Client reader проверяет version1, точную длину, count<=4096, координаты0..254 и kind1..3. Невалидный snapshot очищает overlay; остальные opcodes передаются оригинальному dispatcher. Renderer использует оригинальный projection/camera pipeline и SDK fillrect для цветных клеток зон. Исторические частицы дыма, световой shader и отдельная flash-анимация не заявлены. Пустой snapshot очищает следующий кадр; в городе зоны не рисуются.

## Ходы, таймеры, журнал и reconnect

`begin_turn(combat, owner, actor_ids) -> tuple[bytes]` вызывается **после** `field.prepare_turn` и восстановления AP. `end_turn(combat, owner, actor_ids) -> tuple[bytes]` вызывается на обычном завершении, таймауте и skipped/dead turn до следующего владельца. Передать полный набор actor IDs владельца, включая уже погибших. Begin списывает ПНВ один раз за реальное `_ability_turns[id]` поколение. End завершается идемпотентно на повторном token владельца.

Flash истекает после полного следующего хода пострадавшего, Vision после10 собственных ходов. Area timers считаются по завершённым ходам владельца бросившего: смерть самого бросившего не замораживает эффект, если у владельца есть другие живые бойцы; полное устранение владельца удаляет области. Бинокль истекает в конце хода использовавшего и сразу прекращает разведку после его смерти. Повторные сообщения/timeout callbacks не сокращают TTL.

`Combat.item_effects` содержит только dict/list/tuple/int/str primitives. Текущий snapshot сохраняет динамические attributes; новый registry/class не нужен. Snapshot тестирует эффекты, срок, выбранный instance, inventory и RNG. Политика попадает в существующий rules_digest, следовательно старые сохранённые battle journals надо штатно завершить/архивировать при изменении каталога/конфига; аккаунты, персонажи, бустеры и их даты в базе сохраняются. Проекция reconnect обязана заново использовать item-aware visibility, не посылать заранее полный enemy roster.

## Бустеры вне боя и при наградах

`item_boosters.use_saved(path, account, ItemAction, *, now=None) -> bytes` — city native33 Use, возвращает private inventory30. В одной SQLite transaction проверяет принадлежащий account pet+instance, уровень, активный таймер, CAS и потребление. Создаёт таблицу `item_boosters` автоматически. Активация внутри боя идёт через `item_effects.use`, к той же авторитетной базе. Wager отвергает активацию. Истечение использует серверное wall time и переживает перезапуск. Семейство заменяется новым; одинаковый активный бустер отвергается без расхода.

`item_boosters.nontransferable(template_id) -> bool`: использовать в продаже магазину, личной лавке/аукционе, почте, clan warehouse transfer, battle ground/loot deposit и прямом обмене. Буcтеры5003–5011 нельзя передавать другому владельцу. Обычные вещи возвращают False.

После каждого события обычного HP damage/kill:

```python
before_xp = dict(combat.experience.totals)
before_kills = len(combat.rank_kills)
# existing damage + XP + rank_kills mutation
item_effects.freeze_experience(combat, before_xp, now=event_wall_time)
item_effects.freeze_rank_kills(combat, combat.rank_kills[before_kills:], now=event_wall_time)
```

Оба hook возвращают `None`. Сейчас они подключены к общему `battle_hazards.apply_damage`, включая attack, мину/огонь и Suicide; локальных повторных вызовов Suicide нет. Trainer масштабирует только новый Fraction delta (+30/50/100%), blocker обнуляет его. Advisor запоминает +5/10/20 для каждой уникальной жертвы в момент убийства, а не по будущему времени settlement. `rank_bonus(combat, killer, victim) -> int` добавить к `kill_points + city_kill_bonus` в `ranks.battle_report`, до уже существующих premium/victory/repeat коэффициентов. Wager прогрессия должна по-прежнему быть исключена на уровне settlement.

## Проверенные границы

- `python -m unittest discover -s tests -p test_battle_item_effects.py -q`: 36 тестов, реальные две account rows общей SQLite, CAS, private projection, TTL/dead owners, LOS, server RNG, snapshot, XP/rank event freeze и rollback после первого успешного SQL write.
- `python tools/verify_battle_item_native.py`: 12 случаев; оригинальные writer/consumer native4E attribute12 с шифрованием и getter, native33 и49 writers и zero-damage4B writers. Пакеты не reset-ят idle-animation через3B ради sight.
- `python -m unittest discover -s tests -p test_battle_item_visuals.py -q`: 7 тестов strict codec, privacy, LOS, intermediate field, темнота, TTL/reconnect и4096.
- `python tools/verify_battle_item_client_native.py`: HP/AP12, binocular10, F7reader10, original SDK renderer2, original inventory double-click6 и city booster9; именно оригинальная GUI policy/writer chain исполняется, managed widgets/flush/финальный renderer callback изолированы. Candidate DLL7753216 bytes, SHA256 `2c472913b2f1e9f5171b89518cba692b624d1d194c70024999baf3024da9794f`. Base SHA256 `ccbb3f9eaca7d92ea36e5ca816ce44af9b86c0f501ffc585adcc61f83d6b1458`; сохраняются все base bytes вне пяти hooks и PE sizes; новые hooks не пересекаются с PE relocation.
- `python tools/verify_battle_item_catalog_native.py`: все11 записей exact merged XML SHA256 `2efd1bca527c9f325737f7e1a0a6aad281a15a5cf71e67c6c876a58709751b40`. Metadata class, AP, name, art path, weight, durability и Flare Grenade/Throwing enums исполнены в exact candidate DLL. Каждая посещённая native instruction сверяется с оригинальной DLL byte-for-byte; XML DOM lookup и managed allocation/conversion изолированы. Это не полный filesystem loader или art pixel QA.
- Автоматические ABI проверки не заменяют multiplayer проверку двумя запущенными game clients. Hosted deploy и настоящий GUI QA выполняются основным процессом после публикации catalog/DLL/assets.
