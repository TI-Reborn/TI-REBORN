## 2026-09-19: звания бойцов

Добавлены 29 оригинальных званий и правила страниц52–54 официального руководства. Начисление за убийства/победу, смерть−5, побег−20 с отменой заработка живого сбежавшего, лимиты по уровню, ограничение званием командира для людей/собак/шахтёров. Простой:1%/сутки до50, офлайн-учёт, ускоренное восстановление; формула ранга отряда применяется к кредитам. По решению пользователя строки минимального уровня жертвы9→14 и10→15 сохранены буквально.

Исправлена ошибка rank00e: оригинальный reader66 вычитает1 из номера звания. Очки передаются знаковым int32, прогресс и ускоренный набор также восстановлены; аналогичные поля передаются в3B, комнате и поиске. Запись очков, здоровья, денег и журнала результата атомарна, возврат в город обновляет звание после победы и побега. Старые сохранения мигрируют автоматически, инвентарь и способности сохраняются.

418 unittest/integration PASS;32 оригинальных x86-проверки66/3B PASS. После последнего изменения обновления города при побеге повторно прошли10 тестов званий. Тесты только на временных базах; визуальная проверка пользователем после перезапуска. RANKS.md содержит источники, таблицы вconfig/ranks.json и допущения: округление, сохранение очков при потолке командира, отсутствие неизвестного антинакрута/бустеров. Иконка ранга отряда отдельно не менялась.

## 2026-09-19: Командный и Стенка на стенку

Руководство p14 подтверждает 2×2 владельца/до3 бойцов и4×4/по1. Оригинальные callback875630/8755BC и writer875118->85F954, лимит85DECC исполнены в Unicorn. Добавлены оба пути входа (поиск BA03, комната C82B/2E), локальное заполнение ботами, команды и общая видимость, смена владельца хода, пропуск погибших, командная победа/ничья, атаки ботов,6 точек размещения на сторону. Полный сетевой подбор реальных клиентов остаётся вне возможностей текущего single-account loopback; порядок владельцев и первый ход задокументированы как местная политика. Подробности и первичные источники: TEAM_BATTLES.md.

Проверки:408 unittest/integration PASS;9 original mode/search/range cases;5 original BattleSettings cases;5 original BattleMemberList counts, включая4/8. Отдельная временная база для тестов, сохранение пользователя не изменялось. Визуальная проверка в игре ожидается после перезапуска пользователем. Предыдущую починку дверей пользователь подтвердил.

## 2026-09-19: upper hangar door stuck in state4

Fixed deferred door states in tools/battle_door_grid.js. Original72dc90 now receives stable1/2 for door-only3/4; original sprite/sound/collision path executes. Recovers already pending door states on attachment. JS adapter boundary tests and14 original native cases passed. Client closed before live patch; restart for visual verification. See DOOR_RECOVERY.md.

## 2026-09-19: closed-door collision and reopen fix

See DOOR_RECOVERY.md. Rejection3D now repeats the authoritative point (the native client skips the first owned-actor point). Launcher synchronizes stable door collision and exposes only an adjacent closed door surface after native visibility refresh. 402 server tests, 31 native cases and adapter boundary/cycle checks passed. Restart launcher; final rendered open-close-open check remains for the user.

> DOG ABILITIES / ACTION RECOVERY 2026-09-19: Manual pages47-48 and client CFG verified nine dog perks, including opening doors at level2 and closing at4. Added missing boolean skills14/19 and shared critical4 to learning; exact manual rank requirements, persistent permissions, all-rank healing, scent presence through walls, deathbite, accuracy/armor/critical effects in Survival. Source Fangs critical5 plus perk; damage x2 and higher-rank cooldown inheritance are explicit local assumptions. Legacy finder13 excluded. F0 alone did not finish native battle wait: rejected3C/3E/81 now also sends one-cell authoritative3D and AP4E; native queue completion clears busy. 402 tests PASS,27 original x86 cases PASS, additional encrypted rejected-move then valid-move regression PASS. Main DB/live process untouched. Restart/new battle and in-game animation/input confirmation required. See DOG_ABILITIES.md and evidence/dog_abilities_native.json.

> WALLS / DOORS 2026-09-19: Fixed invisible walls: native resource basename lookup424D7C strips backslash/colon only, so POSIX subdirectory names were missed; packet35 now emits basename without extension. Density increased to3-4wall fragments and6-9cover fragments. Original .t readers749B30/74A9D8 extract translated door cells from hangar/m_house/village_house models. Native3E request and3F reply integrated with persistent per-battle open/closed state,1AP native cost, movement/LOS collision, turn/ownership/range/AP/occupied-door validation; bots open route doors, fogged updates deferred until seen. User explicitly clarified open stays open until manually closed. 394tests PASS including encrypted transport;10 original x86 door/path/cost cases PASS. No client file hooks/patches, mainDB or running game changes. Restart/new battle for visual validation. See BATTLE_MAPS.md and evidence/battle_doors_native.json.

> RESERVATION MAPS 2026-09-19: User requests random scenes and specifies hangars, walls, houses. Survival now generates fresh 38x38 village-ground scenes from validated original fragments; forest reserved in disabled Denver profile. Size documented for TrueSkill Survival in official 2013 contest, not proven universal for all city modes. Local placement/count policy with non-overlapping reservations, clear spawn pockets, BFS connectivity and reachable crates; bounded retries. Per-match seed and object list logged, crate contents pre-rolled with separate RNG, temporary loot persistence invariant retained. Bots explore public waypoints when enemies hidden, no hidden actor targeting or visibility leak. 388 tests PASS including 100 seeds; original ti.exe38x38 ground reader PASS. Player DB/live client untouched. Restart and new battles required for visual check. See BATTLE_MAPS.md.

> CRATE VISUAL 2026-09-19: User confirmed live looting works. First successful opening now sends native44 x y 01 00 before47, once per crate per battle. ti.exe6F5D7A consumes4 bytes (silver961F60 only2),72DC90 sets visible4/offscreen2,72D64C selects base_frame+1;72FF35 settles visible4->2. Original steel_box01/01b resources retained with orientation; no new graphics/DLL edits/hooks. Empty/reopened crate remains open, new battle resets. 385 full tests and4 original x86 visual-state/frame cases PASS. Main DB/game untouched; restart/new battle for user visual test. See BATTLE_LOOT.md and evidence/crate_visual_native.json.

> BATTLE CRATES 2026-09-19: Native46/47/40 connected to Survival with four actual steel-box positions imported from .s fragments. Original AP costs4 first opening/1 reopen; 18-place bag with weight and existing stack rules. Random client-derived ordinary equipment/ammo/medical pool is explicitly provisional in config/battle_loot.json; exact historical drops unknown. All loot IDs, including splits, stay battle-local and are excluded from every SQLite inventory write, including equip/consumption, so finish/disconnect cannot export them. Permanent supplies remain separate; abandoned own supplies are removed and pickup restores them. Added battle armor equip2AP and compatibility/defense projection. Strict turn/ownership/range/quantity/CAS checks and authoritative bag refresh on transfer rejection. 384 tests PASS, including14 loot and encrypted transport integration;8 original x86 writer/consumer-to-window/AP cases PASS. Player DB and live game untouched by tests; restart required, visual test pending. See BATTLE_LOOT.md.

> WEIGHT 2026-09-19: Implemented source item weights including worn equipment and stack quantities, city66/4E and battle3B/4E updates. Manual bases human1000/dog150/miner1000; generic +50/level plus learned carry perks. Native thresholds inclusive50/66.6/80/100 percent confirmed by execution. Penalties0/3/6/9/12: endpoints documented, middle6/9 reconstructed in config/weight.json; common growth for dogs/miners is an interpretation of generic guide text. Each turn uses original AP maximum minus current overload, no cumulative loss or mid-turn refund.370 tests PASS; native19 boundary+3 inventory+3 status cases PASS. Main save untouched, no new client hooks; restart and in-game verification required. See WEIGHT.md and evidence/item_weights.json.

> ITEM STACKING 2026-09-19: User requested ammunition (except Missile8), plus Bandages9/Candies34 only. tio/item_stacking.py merges equal loose metadata per location; shop/SC purchases and6B transfers atomic, destination ID preserved, capacity checked after merging, partial quantities conserved, absorbed IDs reserved. Login migration before roster uses item_stack_backups for old snapshots and is idempotent; no runtime read-side/battle migration. XML stackable9/34=1,8=0; generator and exact legacy catalog recovery updated. Stack sales use unit quantity/prorated pack price; Candies original13HP/1AP connected to existing medical consumption.362 tests PASS;8 native metadata/count/dialog-gate/warehouse cases PASS. Separate saved DB copy38->31 warehouse slots, miner5->4; quantities/metadata/wallet unchanged. Main player DB untouched, restart required; visual verification pending. See ITEM_STACKING.md.

> HOSPITAL PRICE FIX 2026-09-19: User saw0cr despite successful treatment. Live client tariff was0; wallet2290 vs screenshot2342 is consistent with52cr for100/126HP. Constructor hook8C9290 installed after Hospital construction, so it never initialized the existing window. tools/treatment_tariff.js initializes immediately and at whole-function entries8C8D0C(painter)/8C8B30(results price). Same config tariff as server. Original Hospital arithmetic reproduces0 and verifies52/50, selected totals, healthy0;13 recovery tests PASS. Live new hooks installed/detached successfully, tariff0->2 persists; player DB/HP not modified. Launcher includes permanent fix; full relaunch/visual verification remains user test. See RECOVERY.md and evidence/hospital_{price_native,tariff_live}.json.

> CITY RECOVERY 2026-09-19:7C no longer requires arena._completed, so health-perk wounds can be treated before any battle. Server validates room/search exclusion, ownership/funds and commits HP+charge together; repeats on healthy cost0. User approved1HP/10seconds outside battle including offline; historical speed/tariff remain unknown. config/recovery.json retains previous local2cr/HP and approved timer. RecoveryStore persists per-pet timestamps/remainders/paused state, caps projected maxHP, avoids full-health time banking and retroactive HP after perks, sends changed66 from city loop; bootstrap accounts for offline interval. Hospital constructor8C9290 now installs same tariff as results719460.350 tests including encrypted observe_game integration PASS; native treatment/HP probes PASS. Existing user game left running, no full live restart/new Hospital-hook verification; main DB untouched by tests. See RECOVERY.md.

> MINER LEARNING UI FIX 2026-09-19: Read-only inspection of running client31212 confirmed AA ranks20/21/22 ordered3,4,1,2, all at actor-level1, all unlearned. Original8AE5C4 hit testing uses (ability column, required-level row), so rank3 shadows rank1 and predecessor gate disables Learn. AbilityLearning._tree now emits first unlearned rank per (ability,required level), or final learned rank when complete; distinct rows24 at2/3/4/5 remain intact. No changes to prices, requirements or client hooks. Native probe executes original click/hit-test, rank gates and8AD160 button writes: old layout fails, all12 new ranks enabled; completed ranks disabled; defense level gate verified; actual server purchases persist in temporary SQLite. 343 unit tests PASS. tools/verify_miner_learning_ui_native.py and evidence/miner_learning_ui_native.json. Player game was inspected read-only; restart emulator/client to load fix. Existing anti-duplicate policy requires reopening learning window after each purchase to obtain a fresh A9 quote.

> STARTUP FIX 2026-09-19: Reproduced access violation605EC8 before city loading on SharedConfig CString "items". Disabling only605F33 interception did not help; removing the40B34B mid-function hook fixed startup. Removed miner_name_encoding.js and its injection entirely. User allowed another name: Shrek is a documented original-community nickname (https://ggeek.ru/forum/obo-vsem/81407-truskill/), NOT a recovered server-generated name. Catalog/hiring use ASCII; migration changes only legacy defaults, preserving player names and all other fields. Two real launches on a SQLite backup completed30/40seconds, loaded town and all6 pets, continued ping replies. Final copy stores Shrek. Original DB untouched during tests; rename applies on next ordinary startup. 342 unit tests and miner x86 probes PASS. Removed obsolete simulated name-hook probe: it did not test Frida relocation and missed this regression. Logs: data/startup-miner-{repro,isolate,fixed,final}.log.

> MINER ABILITIES 2026-09-19: Four ranks each of20/21/22/24 connected. Manual p48-49 actor requirements; passives HP/carry and defense only without worn armor. Slash335 at7AP hits surrounding actors with manual125/145/160/170%, status/cooldown3, skill22 result4B, turn/ownership/CAS checks. Higher-rank cooldown remains explicit local assumption; raw CFG values conflict and are preserved in raw import. User authorized a new economy after original prices could not be recovered: bases300/250/500/350, rank multipliers1/3/8/20, 5% surcharge per total learned rank, ceil. Requotes atomic with wallet/state. Conditional Cyrillic name reader fix. 341 tests + original x86 probes PASS; main DB untouched, restart/client visual verification pending. See MINER_ABILITIES.md.

> MAP TRAVEL 2026-09-19: Replaced instant movement with durable timed routes, original1D(false)/1E and native float smoothing. F0/97 leaves town; services/hiring blocked outside town; arrival restores C82D/F098/F0117. Reroute and relog resume current position, offline time continues. Restored town9 original towns.cfg bounds(-90,-460,-64,-434), center(-77,-447), northeast of Reservation; manual p12 describes town but does not provide numeric coordinates. MAP_SPEED3 retained from local bootstrap, historical speed unknown. New/existing resource6 pets renamed exactly Шахтёр at server startup, other fields preserved. 332 tests and miner/map-motion original-x86 probes PASS. Restart client/server for live visual test; main DB untouched by automated checks. See MINERS.md.

> MINER HIRING: Mine town9 at user map marker; original1B click/1D response, saved location; atomic town-restricted hire6 for3500 credits, 98HP/14AP/8sight/1000carry. Miner resource/model, squad/Survival/fists337 and Freak equipment checks connected. 327 tests + native1B/1D/62/66 PASS. User must restart and test map entrance/hire/render; mining battles/perks not implemented. See MINERS.md.

## Проверка действующего пути действий предмета

### Что исследовано
Callers992294, action997260, interface adapter999ad7->99b230, new window920068->921118.
### Что доказано
Original997260 выполнил920068(selecteditem1001) и вернулся; расположенный ниже6B sender не выполняется. RTTI91e8d2 точно TGUI_SupplementWindow.
### Новые packet mappings
Нет. Предположение об экипировании через этотcallback отклонено; это путь пополнения.
### Новые структуры
RTTI окна содержит initial/warehouse/shop item и состоянияPurchase/ExchangeRequested/Complete.
### Изменённые файлы
verify_item_action_route_native.py, evidence/item_action_route_native.json, документация.
### Добавленные тесты
Native callback до возврата PASS, guard на недостижимый legacy6B, RTTI class assertion. Unit suite не менялся (139 последних успешных).
### Что остаётся неизвестным
Штатный callback экипирования, семантика остальных6B режимов, серверное изменение слота.
### Риски и альтернативы
Destination window/UI изолированы; native доказывает маршрут, не результат действия пользователя.
### Следующий самый полезный шаг
Найти конкретное действие экипирования в конструкторе меню/drag-drop и его sender, исключив supplement и недостижимый legacy code.

## Групповой запрос предметов

### Что исследовано
SquadPage путь993da0, builders990304/9903a4/992444 и992294.
### Что доказано
Оригинальный992294 пишет6B,modebyte,identityu32, два списка(u16count, парыinstance/count).3native layouts PASS, реальные writers; managed arrays/UI изолированы.
### Новые packet mappings
6B envelope codec добавлен. Режим и назначение списков UNKNOWN; не считать подтверждённым экипированием.
### Новые структуры
ItemBatch(mode,identity,first,second). Проверка длины, усечений и хвоста.
### Изменённые файлы
item_batch.py, verify_item_batch_native.py, test_item_batch.py, evidence/item_batch_native.json, документация.
### Добавленные тесты
139tests PASS; original fixtures0/1/2 entries и malformed lengths.
### Что остаётся неизвестным
Семантика режима/двух списков, UI equip binding, server mutation и ответ.
### Риски и альтернативы
32 также содержит триu32 и вызывается рядом с продажей; это не доказательствоequip.33 проверяет usable metadata.6B пока не маршрутизируется к записи в БД.
### Следующий самый полезный шаг
Проследить конкретный drag/drop equip callback к992294 или другому sender и определить управляющие параметры.

## Инвентарь: признак экипирования и слот

### Что исследовано
RTTI TANetItemListElement611ff5; getEquipped6125de->63c770, getSlot61261b->63c7d0; consumer99080a/990825.
### Что доказано
equipped передаётся отдельным byte, slot=u32. Native99082a..9908b4 нормализует800/1000/2000 в4;8casesPASS. НачальнаяBeretta301 имеетequipped0,slot0.
### Новые packet mappings
Имена существующих полей30 подтверждены; новый запрос экипирования пока не найден.
### Новые структуры
ItemRecord.equipped,slot,client_slot,count aliases. Diagnostic actor projection принимаетinventory, переносит толькоequipped1 templateIDs по проверенным masks.
### Изменённые файлы
item_list.py, battle_actor_fixture.py, loopback_exchange.py, verify_inventory_slots_native.py, test_battle_actor_fixture.py, evidence/inventory_slots_native.json.
### Добавленные тесты
138tests PASS: backpack не экипируется, оборудованныйslot1 переносится, duplicate/unknown/noncanonical/foreign inventory отклоняются; native normalization8cases.
### Что остаётся неизвестным
Запрос экипирования и live перенос оружия, item restrictions и полный боевой процесс.
### Риски и альтернативы
Проекция толькоtemplateID, не полноценные durability/ammo/модификации. База не изменялась, стартовый предмет не экипируется автоматически.
### Следующий самый полезный шаг
Найти исходящий запрос экипирования изSquadPage и подключить сохранение нового состояния с ответом30.

## Боевая экипировка: поля и размещение

### Что исследовано
Оригинальные вызовы98f978 из3B и распределение записей по model offsets.
### Что доказано
11 значений template ID прочитаны оригинальным3B и распределены98f978 в12 записей. Mask0x10 копируется в+df0 и+1080.
### Новые packet mappings
Нет нового opcode; подтверждены equipment fields существующего3B.
### Новые структуры
BattleSoldier.equipment_templates возвращает mask->templateID для human profile. Masks1,2,10,80,4,8,400,40000,80000,100000,200000(hex).
### Изменённые файлы
battle_soldier.py, trace_battle_soldier_native.py, verify_battle_equipment_native.py, test_battle_soldier.py, evidence/battle_equipment_native.json.
### Добавленные тесты
136tests PASS; native11dispatch/12destination records, codec сопоставлен с evidence.
### Что остаётся неизвестным
Соответствие ItemList.location_raw слотам, экипирование/снятие, рендер оружия и боевые действия.
### Риски и альтернативы
Managed copy изолирован, marker IDs структурные. Данные инвентаря не изменяются; нельзя считать предмет в рюкзаке экипированным.
### Следующий самый полезный шаг
Восстановить городское размещение предметов и запрос экипирования, затем переносить только экипированные вещи в3B.

## Арена: живой боец в сцене

### Что исследовано
Соответствие полей66/3B по одинаковым model offsets и wire widths; полный live consumer8c5044.
### Что доказано
LIVE: battle_actor_return id1,owner1,level1,hp100,maxhp100,x2,y2; scene_finalize_return4 иC2S36. Exit0 после12секунд, ошибок Frida нет.
### Новые packet mappings
3B после35 перед41 принят оригинальным клиентом. Start2E ещё не подключён.
### Новые структуры
Diagnostic bare actor копирует identity/name/resource,appearance и44 одинаковых model destinations из66; остальные боевые поля временные нули. Нет переноса inventory equipment.
### Изменённые файлы
battle_actor_fixture.py, launcher/capture/loopback, tests/test_battle_actor_fixture.py, test_reservation_launcher.py; evidence/battle_actor_field_mapping.json, battle_actor_live.log/summary.
### Добавленные тесты
135tests PASS. Изменённые identity17/owner42/level3/HP73of120 сохраняются при проекции, mainDB probe запрещён.
### Что остаётся неизвестным
Отображение бойца, equipment/actions/turns, serverStart и полный функционал города.
### Риски и альтернативы
Same-offset mapping подтверждает хранилище, но не всю игровую семантику. Bare actor только диагностика, не полноценный боевой состав. Наблюдали native return, не UI.
### Следующий самый полезный шаг
Проверить ti.exe модель/отображение, перенести экипировку и подключить Start2E к боевой lifecycle.

## Живая загрузка сцены арены

### Что исследовано
Сервер35/41 после native создания комнаты, реальные handlers ti.exe.
### Что доказано
Resources return2, ground return2, loadend return3, finalize return4, сервер получил36. Live12seconds exit0, ошибок Frida нет.
### Новые packet mappings
35/41->36 проверено в клиенте; Start2E ещё не связан.
### Новые структуры
Локальная пустая карта8x8, два нулевых слоя, без объектов и бойцов.
### Изменённые файлы
run_reservation.py, capture_loaded_orange.py, loopback_exchange.py, test_reservation_launcher.py, evidence/battle_scene_live.log/summary и отдельная база.
### Добавленные тесты
134tests PASS; изоляция scene probe от основной базы,ready/leave,мутаций.
### Что остаётся неизвестным
Видимый результат, actor3B, бой и полный функционал города.
### Риски и альтернативы
Native create не UIclick. Пустая сцена доказывает handshake, не игровой процесс. Только явный диагностический флаг.
### Следующий самый полезный шаг
Добавить корректного бойца3B, проверить создание модели и затем связать Start.

## Арена: завершающий пакет загрузки

### Что исследовано
ti.exe7175ac ресурсный ground.xml, ссылки на loading state76deb4, dispatcher7182c0 и718138.
### Что доказано
S2C41 (0x35+0x0c) вызывает718138 и ставитstate3 без чтения тела. Два новых native случая исполнили реальный dispatcher41 затем completiongate: pending0 ->state4/36, pending1 ->state3/no-send.
### Новые packet mappings
S2C41 без тела encode_battle_load_end; связывает завершение передачи данных с ожиданием ресурсов и C2S36.
### Новые структуры
ground.xml содержит7 типов декоративного покрытия. Read-only audit: IDs0..4 все зависимые brush файлы присутствуют;5 отсутствуют32/32;6 отсутствуют21/27. Это не готовый серверный layout.
### Изменённые файлы
battle_loaded.py, verify_battle_loaded_native.py, test_battle_loaded.py, audit_battle_ground_resources.py, evidence/battle_loaded_native.json, battle_ground_resources.json, документация.
### Добавленные тесты
133 unittest PASS; native completion теперь6cases (включая dispatch41), member4cases. Сравнение packet41 с native evidence включено.
### Что остаётся неизвестным
Полныйlive35/3B/41, валидные значения слоя карты и выбор scene mode, настоящие бойцы и ходы.
### Риски и альтернативы
Native resource pending count иscene finalization изолированы; наличие файлов не гарантирует загрузку. Пакет41 не запускает бой сам по себе и не подключён к серверной lifecycle.
### Следующий самый полезный шаг
Подготовить отдельную live-диагностику последовательности35/3B/41 и наблюдать36, используя установленный полный набор ресурсов.

## Арена: сцена карты и подтверждение загрузки

### Что исследовано
ti.exe717e1c второй consumer35, load completion717de0 ->7186b4; silver95e050 member-loaded37.
### Что доказано
Native3rectangles: оба слоя записываются в scene cells stride14 (+8 first,+0 second), размеры и флаг первого byte==1 записаны. Native zero-width probe входит в cellloop приwidth0. Completion4cases: толькоstate3/pending0 переходит4 и отправляет36. Member4cases:37u32ID выставляет+111 только найденному occupied member.
### Новые packet mappings
C2S36 без тела; S2C37u32characterID. Codec готов, серверная боевая lifecycle интеграция ещё отсутствует.
### Новые структуры
Сцена использует оба слоя35, entries передаются6cd690(name,x,y). Флаг+111 контекстный: в комнате использовалсяown, приloaded37 выставляется для любого member; не называть его универсальноown.
### Изменённые файлы
tio/protocol/battle_loaded.py, battle_ground.py; tools/verify_battle_loaded_native.py, verify_battle_ground_scene_native.py; tests/test_battle_loaded.py, test_battle_ground.py; evidence и документация.
### Добавленные тесты
133 unittest PASS; native4completion+4member cases,3scene grids+zero-width hazard. Groundcodec отвергает нулевые размеры и names>255 из-за ti.exe shortstring.
### Что остаётся неизвестным
Загрузка ресурсов7175ac, переход кstate3, реальные модели карты, полныйliveStart/бой.
### Риски и альтернативы
Resource pending count предоставлен в native изоляции; финализация сцены/transport endpoints изолированы. Scene probe остановлен до7175ac, не подтверждает отображение. Старый silver0x0 fixture остаётся доказательством только partialreader и теперь отклоняется codec.
### Следующий самый полезный шаг
Разобрать7175ac и ресурсные имена карты, связать получение35 соstate3 и проверитьlive на отдельной базе.

## Арена: боевые записи бойцов

### Что исследовано
Dispatch8c7edc и BattleSoldierAdd reader8c5044 до8c5aab; общий appearance reader6d01f8, ветви экипировки и временных состояний.
### Что доказано
Opcode3B ->8c5044. Восемь структурных native случаев, шесть повторов кодированных пакетов с маркерами прошли. Оригинальные числовые readers записали owner1/2,level5,position31/47 и own flag; расход тела совпал. Структурные тела201..251bytes в выбранных профилях.
### Новые packet mappings
S2C3B кодируется/декодируется отдельно от66. Static adjacent42 update и43 delete ещё не реализованы.
### Новые структуры
BattleSoldier с внешним human_equipment и полями по адресам чтения. Семантические свойства soldier_id,owner_id,level,position. Float32 хранятся как raw bits. Четыре timed extensions включаются только при1; appearance и flag43 при ненулевом значении.
### Изменённые файлы
tio/protocol/battle_soldier.py, tools/trace_battle_soldier_native.py, tools/verify_battle_soldier_native.py, tests/test_battle_soldier.py, evidence/battle_soldier_native_variants.json и battle_soldier_replay.json, документация.
### Добавленные тесты
131 unittest PASS: native fixtures, усечения, лишние/отсутствующие поля, явный профиль экипировки, сверка marker replay с записанной native моделью.
### Что остаётся неизвестным
Большинство числовых полей, валидная карта/ресурсы и последовательность загрузки сцены; live3B и полноценныйStart отсутствуют.
### Риски и альтернативы
Native останавливается после чтения, до8c5aab уведомлений сцены. Выделение памяти/ресурсы/строки изолированы; нулевые тела структурные, не игровые. В бою3B заменяет запись модели, но не является66 для городского roster.
### Следующий самый полезный шаг
Найти остальные потребители карты35, загрузку сцены и подтверждение loaded37; затем объединить сStart, не выдавая отдельные пакеты за рабочий бой.

## Арена: команда старта и формат поля боя

### Что исследовано
Owner callback81db34, buildera08ab0 и dispatch96244c/reader95dd78 BattleGround.
### Что доказано
Native builder формирует2E без параметра приAL=255 и2E00/01/02 для выбора режима16. Original reader35 читает размеры, два слоя и именованные записи;4 случая завершились с точным расходом тела и ожидаемой записью второго слоя в сетку.
### Новые packet mappings
C2S2E: optional selection только дляmode16. S2C35: dispatch962470 ->96256b ->95dd78. Декодеры добавлены, запуск боя в сервер ещё не подключён.
### Новые структуры
BattleGround: unknown_u8,width,height,first_layer[width*height],u16 count, entries(CString,u8,u8),second_layer[width*height]. Назначение значений слоёв и полей entries UNKNOWN.
### Изменённые файлы
tio/protocol/arena.py, battle_ground.py; tools/verify_room_actions_native.py, verify_battle_ground_native.py; tests/test_arena.py, test_battle_ground.py; evidence/room_actions_native.json, battle_ground_native.json; ARENA.md, NEXT_TASK.md.
### Добавленные тесты
129 unittest PASS: проверка native fixtures, размеров, усечений, лишних данных, максимального кадра, соответствия вариантаStart режиму комнаты. Native ground4cases PASS; actions8cases PASS.
### Что остаётся неизвестным
Полная последовательность начала боя, загрузка сцены, значения карты, состав BattleSoldierAdd, подтверждения загрузки и ходы.
### Риски и альтернативы
В native проверке изолированы выделение памяти/строк и ресурсы, таблица31 моделей пуста. Реальный35 удаляет эти модели перед чтением. Нельзя выдавать standalone35 за восстановленный запуск боя или проверку интерфейса.
### Следующий самый полезный шаг
Восстановить загрузку сцены и BattleSoldierAdd, затем связать их сStart. Область задачи — все функции города, как уточнил пользователь.

## Арена: выход из комнаты

### Что исследовано
Native81db8c ->2A01, серверный leave ->F0 command24 zeroargs ->client cleanup7d4a88.
### Что доказано
LIVE: arena_left remaining_rooms0; room_leave_return occupied0/owner0, exit0. Готовность переключалась перед выходом.
### Новые packet mappings
2A01 подключён; F0/24 без аргументов проверен живым клиентом. Альтернативный2A00 остаётся неподдержанным.
### Новые структуры
Нет; используются существующие registry/records.
### Изменённые файлы
arena.py, system_message.py, arena_service.py, loopback_exchange.py, run_reservation.py, capture_loaded_orange.py, tests и evidence/arena_leave_live.log/summary.
### Добавленные тесты
Malformed leave не меняет room, повторныйleave безопасен, re-create послеleave, отдельная база probe.126tests PASS.
### Что остаётся неизвестным
Штатный UI и multiclient departure, Start/бой, реальные параметры статусов.
### Риски и альтернативы
Native callback — не UIclick. Owner departure закрывает комнату по локальной политике; рассылка нескольким клиентам ещё не реализована.
### Следующий самый полезный шаг
Восстановить owner Start a08ab0 и переход к боевой сессии.

## Арена: живая готовность и команда выхода

### Что исследовано
Native ready toggle81dae8 через сервер2C; SystemMessage switch7d1d98.
### Что доказано
LIVE ready0->1->0 с неизменным roster, exit0. Static CONFIRMED command24: selector7d1db4[24]=23, jump table7d1fbf[23]=7d2661, вызывает7d4a88 ->clear8members ->7d0c84 закрытие окна.
### Новые packet mappings
F0/24 — ветка очистки/закрытия комнаты; полный live-response ещё не проверен.
### Новые структуры
Нет.
### Изменённые файлы
run_reservation.py, capture_loaded_orange.py, test_reservation_launcher.py, evidence/arena_ready_live.log и summary, документация.
### Добавленные тесты
Изоляция --probe-arena-ready (отдельная база, включает nativecreate). 125tests PASS, live8seconds.
### Что остаётся неизвестным
Аргументы/полныйliveF0/24, старт боя, штатныйUI.
### Риски и альтернативы
Диагностически вызвана non-owner ready функция; кнопка владельца запускает другую ветку. Готовность не означает запуск боя.
### Следующий самый полезный шаг
Проверить F0/24 в живом клиенте и подключить выход2A01.

## Арена: готовность участника

### Что исследовано
Кнопкаready81f035 ->81db34; non-owner81dae8 ищет ownID и инвертирует ready. Native buildera08a80. Leave81db8c ->a08a20.
### Что доказано
CONFIRMED original writers: ready2C01/00; leave button2A01 (EAX0), альтернативныйEAX1 даёт2A00, семантика альтернативы UNKNOWN.
### Новые packet mappings
C2S2C strictbool подключён к server readiness, ответ25(flag1). Leave2A пока не подключён.
### Новые структуры
ArenaService хранит актуальные member records; повторный create сохраняет ready и возвращает текущее значение.
### Изменённые файлы
arena.py, arena_service.py, loopback_exchange.py, test_arena_service.py, native verifiers и evidence/room_actions_native.json, документация.
### Добавленные тесты
Четыре originalwriter/callback случая; readyon/off/repeat, malformed, foreignID, afterdisconnect, duplicatecreate. 125tests PASS.
### Что остаётся неизвестным
Live готовность, reply выхода, owner start/боевая сессия.
### Риски и альтернативы
Ready не запускает бой. Кнопка владельца имеет отдельную веткуa08ab0; не смешивать с non-owner ready.
### Следующий самый полезный шаг
Проверить native ready toggle в живом клиенте и восстановить ответ выхода.

## Арена: сохранённый отряд в комнате

### Что исследовано
Сохранённые66 snapshots, проекция level/NPC и серверный create response.
### Что доказано
LIVE: native create -> серверный roster -> room_open_return -> member soldier level1/npc1/equip1/avatar0. Процесс exit0. Реальные level/NPC взяты из полей66, а не заданного по умолчанию шаблона.
### Новые packet mappings
Новых нет; заполнена group1 списка25.
### Новые структуры
arena_roster.room_soldiers: первые активные сохранённые бойцы в порядке petID, до выбранного лимита. Это локальная политика выбора до восстановления выбора состава.
### Изменённые файлы
arena_roster.py, arena_service.py, loopback_exchange.py, capture_loaded_orange.py, test_arena_roster.py, evidence/arena_roster_live.log и summary, документация.
### Добавленные тесты
Сохранённые level/resource, фильтр state0, лимит, ключ actor. 124tests PASS и live8seconds.
### Что остаётся неизвестным
Полное вычисление equip/injury/avatar/ranks, явный выбор состава, ready/start/leave, видимый интерфейс.
### Риски и альтернативы
Совместимость явно частичная: human resources1/2; equip1,injury0,avatar/ranks0 временные. Эти значения не доказывают реальное состояние экипировки/травм. Бой не запущен.
### Следующий самый полезный шаг
Восстановить действия комнаты и выбор состава, затем заменить временные состояния.

## Арена: отображение состояния бойца

### Что исследовано
TUnitStatus RTTI a0cec2 и DrawEquipStatus a0fc6c; owned66 destinations8c44a6/8c4aef.
### Что доказано
CONFIRMED: equip1..4 выбирает sprites4..7; прочие значения sprite4. injury>0 выбирает красныйffff7777, ноль — белыйffffffff. Owned model имеет другую структуру: level+5ffc, name+5ff4; прямое копирование TUnitStatus некорректно.
### Новые packet mappings
Нет.
### Новые структуры
Уточнена визуальная обработка equip/injury.
### Изменённые файлы
tools/verify_unit_status_native.py, evidence/unit_status_native.json, документация.
### Добавленные тесты
Native verifier исполняет DrawEquipStatus с изолированным renderer для equip0..5 и injury0/1/255.
### Что остаётся неизвестным
Связь состояний/ranks с owned66; автоматическое заполнение состава остаётся незавершённым.
### Риски и альтернативы
Значок не доказывает смысл каждого equipment enum. Нельзя выводить equipStatus только из наличия предмета.
### Следующий самый полезный шаг
Найти оригинальное преобразование owned pet в UnitStatus либо поля owned66 по метаданным.

## Арена: исходные имена структуры состава

### Что исследовано
Original Delphi RTTI61c229..61d268; field offsets и method pointers; отображение81fa..8204.
### Что доказано
CONFIRMED group1 fields: level,equipStatus,injureStatus,npcId,avatarId,rank,militaryRank,pointsToNextRank. Отдельного petID нет. Member prefix: crestId,avgLevel,level,color,team,ready,online. Group2: soldierName,level,maxHp,pDefence,equipStatus,npcId,avatarId,rank,militaryRank,pointsToNextRank,weaponItemId children.
### Новые packet mappings
Уточнены имена полей25 по исходным метаданным.
### Новые структуры
Семантические свойства codec и MemberGroup1.soldier factory; исходные wire-поля сохранены.
### Изменённые файлы
battle_members.py, arena_service.py (online1 вместо0), test_arena_service.py, verify_battle_member_rtti.py, evidence/battle_member_rtti.json, документация.
### Добавленные тесты
Восемь group1 field offsets и getter pointers сверены с pinned binary; server reply проверяет ready0/online1. 123tests PASS.
### Что остаётся неизвестным
Связь состояния экипировки/травм с owned66, заполнение отряда, действия боя.
### Риски и альтернативы
Имена раскрывают смысл, но не допустимые значения equipStatus/injureStatus. Не считать avatarId идентификатором наёмника.
### Следующий самый полезный шаг
Использовать RTTI для остальных неизвестных полей и связать сохранённый отряд с soldierInfo.

## Арена: живая цепочка создания

### Что исследовано
Native a0a6f4 в клиенте -> транспорт -> серверный ArenaService ->6C/25 -> открытие комнаты.
### Что доказано
CONFIRMED live: запрос C8/2B получен, arena_room_created зарегистрирован, клиент завершил room_open и member consumer (slot0/id1/own1). Процесс завершился exit0.
### Новые packet mappings
Новых нет; проверена интеграция существующих.
### Новые структуры
Нет.
### Изменённые файлы
run_reservation.py, capture_loaded_orange.py, test_reservation_launcher.py, evidence/arena_create_live.log и summary, документация.
### Добавленные тесты
Изоляция --probe-arena-create: отдельная база, запрет canned battle replies и конфликтующих проб. 123tests PASS. Live8seconds.
### Что остаётся неизвестным
Видимое окно/штатная кнопка, заполнение бойцами, ready/start/leave и полноценный бой.
### Риски и альтернативы
Запрос выполнен native builder через диагностический вызов, не кликом. Ответ использует документированный временный compatibility profile.
### Следующий самый полезный шаг
Восстановить заполнение комнаты собственными бойцами и проверить доступные действия комнаты.

## Арена: сетевой обработчик создания

### Что исследовано
Текущий loopback dispatcher, управление выбранным персонажем и завершение потока.
### Что доказано
Реализован C8/2B -> ArenaService -> waiting room ->6C/25. Identity берётся из выбранного персонажа, не запроса. Проверены ответы и отсутствие mutations при malformed/name/wager errors.
### Новые packet mappings
Подключён ранее подтверждённый C8/2B; ошибки через существующий общий394.
### Новые структуры
ArenaService связывает модель и codec. Объект комнаты удаляется после завершения серверного потока.
### Изменённые файлы
tio/arena_service.py, tools/loopback_exchange.py, tests/test_arena_service.py, документация.
### Добавленные тесты
Выбранные параметры/identity в ответе, duplicate create, disconnect, malformed packet, неподдержанный режим/ставка, ошибочное имя до mutation. 122tests PASS.
### Что остаётся неизвестным
Live end-to-end создания, бойцы в комнате, старт боя, join/leave wire, значения оставшихся полей.
### Риски и альтернативы
Экспериментальный профиль: unknown40=1 (НЕ roomID), unknown1f=2, неизвестные уровни0/0, зона выхода0. Лимит хода20*soldiers+20 — временная локальная политика по формуле формы; серверный оригинал не доказан. Поддержаны modes0/1/4/8 и1..3soldiers. Ставки отклоняются, кошелёк не меняется.
### Следующий самый полезный шаг
Вызвать original create builder в диагностическом клиенте и проверить всю новую цепочку до room-open; затем добавить отряд.

## Арена: серверное состояние комнат

### Что исследовано
Оставшиеся offsets6C:1f сравнивается с member+10f при стрелках изменения состава; точная семантика пока UNKNOWN. Для1d/1e/40 прямых чтений рядом с ac6008 не найдено; это не доказательство отсутствия использования.
### Что доказано
Добавлена отдельная серверная модель ожидающих комнат с owner/request/members, созданием, присоединением и выходом.
### Новые packet mappings
Нет. Registry пока не подключён к сети.
### Новые структуры
WaitingRoom и ArenaRooms; состояние в памяти процесса, immutable snapshots, синхронизация RLock.
### Изменённые файлы
tio/arena_rooms.py, tests/test_arena_rooms.py и документация.
### Добавленные тесты
Повторное создание, конфликт membership, конкурентное заполнение последнего места, выход/освобождение участников, уникальность room IDs, отказ неподдержанного wager без изменения состояния. 120 tests PASS.
### Что остаётся неизвестным
Соответствие оставшихся настроек; wire-интеграция и полный бой.
### Риски и альтернативы
Закрытие комнаты при выходе владельца — локальная политика, не восстановленное правило оригинала. Ставки пока отклоняются, списаний нет. Room ID внутренний и не приписан неизвестному wire-полю.
### Следующий самый полезный шаг
Подключить C8/2B к registry и проверенной последовательности6C/25, затем штатно проверить комнату.

## Арена: полный обработчик подтверждения создания

### Что исследовано
85d658 до возврата, включая a0a6f4 и исходный serializer; поле acf068, подпись m617.
### Что доказано
CONFIRMED: исходящий последнийu32 — ставка. Создание переносит mode/map/players, фиксированное2, вычисленное20*soldiers+20, два soldiers, levels-1, stake. Проверено оригинальным исполнением на двух наборах параметров.
### Новые packet mappings
Уточнён последнийu32 C8/2B как stake.
### Новые структуры
ArenaCreateRequest.stake сохраняет совместимость с исходным неизвестным именем поля.
### Изменённые файлы
tio/protocol/arena.py, tools/verify_arena_create_form_native.py, evidence/arena_create_form_native.json, документация.
### Добавленные тесты
Два native-сценария полного callback с UI fixtures; сериализация и арифметика исходные.
### Что остаётся неизвестным
Назначение остальных неизвестных полей, состояние комнаты на сервере, штатная UI-проверка.
### Риски и альтернативы
UI lookup/track reads/string parsing заменены фиксированными значениями. Формула20*soldiers+20 сама по себе не доказывает семантику времени.
### Следующий самый полезный шаг
Завершить соответствие настроек и реализацию серверного создания комнаты.

## Арена: значения настроек комнаты

### Что исследовано
Конструктор81f2a6 и updater81dd88: две таблицы ветвления восьми строк window_battleroom_info, подписи russian.lng.
### Что доказано
CONFIRMED settings offsets: +24 создатель, +19 тип игры, +20 размер карты, +1 число игроков, +1c число солдат, +14 лимит хода в секундах, +28 зона выхода (подпись вычисляется через2-value), +2c ставка.
### Новые packet mappings
Уточнены поля6C, новых opcode нет.
### Новые структуры
BattleSettings получил читаемые свойства для подтверждённых значений; wire layout сохранён.
### Изменённые файлы
tio/protocol/arena.py, tools/verify_battle_settings_labels.py, evidence/battle_settings_labels.json и документация.
### Добавленные тесты
Static verifier проверяет оригинальные таблицы, адреса ключей локализации и инструкции чтения полей на закреплённом SHA клиента. 116 unittest PASS.
### Что остаётся неизвестным
Поля1d/1e/1f/40; полное соответствие запросу создания, серверный жизненный цикл.
### Риски и альтернативы
Подпись интерфейса определяет назначение, но не диапазон допустимых значений и правила сервера.
### Следующий самый полезный шаг
Сопоставить параметры C8/2B с подтверждёнными настройками ответа6C.

## Арена: переход к комнате ожидания

### Что исследовано
a0a3df -> 66754c -> 7d0be8 -> 81d37c; live25 с flag0.
### Что доказано
CONFIRMED: flag0 и gate1 вызывают переход; flag1, gate0 и mode12 подавляют его. В живом клиенте: member enter -> transition(context_count3) -> room open(enabled1) -> room open return -> member return.
### Новые packet mappings
Уточнён заголовочный флаг25: ноль разрешает проверку перехода после обновления состава.
### Новые структуры
Нет.
### Изменённые файлы
loopback_exchange.py, capture_loaded_orange.py, verify_battle_member_consumer_native.py, evidence/battle_transition_live.log и summary, документация.
### Добавленные тесты
Четыре комбинации флага/состояния/mode12 в native verifier, всего8 сценариев. 116 unittest PASS. Live8 секунд, отдельная база, exit0.
### Что остаётся неизвестным
Видимый результат, штатная кнопка создания и серверный жизненный цикл комнаты.
### Риски и альтернативы
Открытие подтверждено исполнением функции, без визуального подтверждения. Диагностический состав пока без бойцов.
### Следующий самый полезный шаг
Подключить создание C8/2B к состоянию комнаты и проверить интерфейс.

## Арена: живой список участников

### Что исследовано
Передача6C затем25 через транспорт в работающий клиент, полный callback a0a29c.
### Что доказано
CONFIRMED: оба обработчика вернулись; settings owner1, таблица участников slot0/id1/own1. Диагностический процесс завершился кодом0.
### Новые packet mappings
Живая обработка25 подтверждена, новых opcode нет.
### Новые структуры
Нет; сверена таблица участников с ранее исследованным layout.
### Изменённые файлы
run_reservation.py, loopback_exchange.py, capture_loaded_orange.py, test_reservation_launcher.py, evidence/battle_members_live.log и summary, документация.
### Добавленные тесты
Изоляция нового --probe-battle-members: основная база запрещена. Все116 unittest прошли. Live --seconds8 с отдельной battle-members-trial.sqlite3.
### Что остаётся неизвестным
Открытие окна через штатное создание, состав бойцов и жизненный цикл комнаты/боя.
### Риски и альтернативы
Пакеты диагностические, вложения пусты; callback-return не доказывает видимый интерфейс или успешное создание комнаты.
### Следующий самый полезный шаг
Проследить открытие window_battleroom и подключить подтверждённую последовательность к C8/2B.

## Арена: преобразование вложенного состава

### Что исследовано
Полная функция a09b78 и её ветки по режиму BattleMemberList25.
### Что доказано
CONFIRMED: modes6/7 преобразуют group2; mode21 пропускает вложения; mode0 использует group1. Каждая ветка ограничивает состав тремя записями. Совпадение characterID с [ac5a98] устанавливает member+111=1 и копирует member+10f в [ac5498].
### Новые packet mappings
Новых opcode нет; уточнён смысл выбора групп списка25.
### Новые структуры
Три вложенных места начинаются с member+120, stride0x28. Названия их полей пока UNKNOWN.
### Изменённые файлы
tools/verify_battle_member_nested_native.py, evidence/battle_member_nested_native.json, ARENA.md, NEXT_TASK.md, WORK_REPORT.md.
### Добавленные тесты
Оригинальный reader создаёт четыре записи каждой группы; оригинальная a09b78 доходит до возврата для modes0/6/7/21. Проверены собственный участник и три результирующих записи. Все 116 unittest прошли.
### Что остаётся неизвестным
Семантика числовых полей вложений, живое открытие комнаты и серверный жизненный цикл боя.
### Риски и альтернативы
Managed copy, строки, события и UI изолированы; числовые getters и преобразование выполняются оригинальным кодом. Это не проверка живого интерфейса.
### Следующий самый полезный шаг
Диагностический live25+6C с собственным участником и наблюдением полного consumer.

## Арена: размещение участников комнаты

### Что исследовано
Closure a0b5d0 вызывает a0a29c; прочитано начало преобразования a09b78.
### Что доказано
CONFIRMED: a0a29c ищет существующий ID среди восьми слотов stride 0x1c0, иначе первое свободное место. При заполнении неизвестный ID пропускается. Заголовок mode12 принудительно устанавливает settings+18=1. После обработки вызывается a0ac58.
### Новые packet mappings
Новых opcode нет; уточнён consumer списка25.
### Новые структуры
Таблица [ac62a4]: флаг занятости +0, character ID +4, восемь записей.
### Изменённые файлы
tools/verify_battle_member_consumer_native.py, NEXT_TASK.md, WORK_REPORT.md, ARENA.md и evidence.
### Добавленные тесты
Четыре native-сценария: вставка, обновление, заполненная таблица, mode12. Все 116 unittest прошли.
### Что остаётся неизвестным
Полное преобразование вложений a09b78 и открытие живой комнаты.
### Риски и альтернативы
Native-проверка изолирует копирование managed record, преобразование записи и UI; это не проверка полного consumer или интерфейса.
### Следующий самый полезный шаг
Завершить a09b78 и проверить согласованный список25 с настройками6C в диагностической сессии.

## Арена: полные вложенные записи25

### Что исследовано
64c2e0,64cb6c,64c980 и typedmemberreader.
### Что доказано
Обе группы иleafu16 прочитаны originalкодом, по2записи и2children, точныйcursor.
Некоторые wireu32 сохраняются вbyte; codec сохраняет32bitзначения.
### Новые packet mappings
Уточнён полный25, НЕ BA0B.
### Новые структуры
BattleMemberRecord,MemberGroup1,MemberGroup2,childwords; поляUNKNOWN.
### Изменённые файлы
protocol/battle_members.py,tests/test_battle_members.py,tools/verify_battle_member_nested_native.py,
evidence/battle_member_nested_native.json,battle_group1_reader.asm,battle_group2_reader.asm,
ARENA.md,NEXT_TASK.md,WORK_REPORT.md.
### Добавленные тесты
Originalnestedreader0/1/2cases PASS, независимыеwirefixtures/усечения/счётчики;
116unittest PASS.
### Что остаётся неизвестным
Семантикаgroups,consumerclosure,live25, открытие комнаты и servercreation.
### Риски и альтернативы
Не интерпретировать неизвестныечисла какID/HP без трассыconsumer.
### Следующий самый полезный шаг
Consumerclosurea0b5dc иlive25+6C.

## Арена: основной список участников25

### Что исследовано
Delayedreceivera0ce08,typeddecoder64e628/64e6b4/64d880,serializer64e720.
### Что доказано
25 отличается отBA0B; header2bytes+u32count,memberprefix с двумя nestedarrays.
Originalnumericreader0/1/2members с пустыми вложениями PASS,cursorточный.
### Новые packet mappings
25→BattleMemberList_Delayed;64e720 явно пишет25.
### Новые структуры
Member0x134, две вложенные группы с native strides0x28/0x13c; назначенияUNKNOWN.
### Изменённые файлы
 tools/verify_battle_member_list_native.py,evidence/battle_member_list_native.json,
battle_member_typed_reader.asm,ARENA.md,NEXT_TASK.md,WORK_REPORT.md.
### Добавленные тесты
3originalreader cases PASS; серверная логика не менялась.
### Что остаётся неизвестным
Непустые вложения,UIconsumer иcreatehandshake; готовность боя не доказана.
### Риски и альтернативы
Нельзя применятьcodecBA0B для25; форматпроверен толькос пустымигруппами.
### Следующий самый полезный шаг
64c2e0/64cb6c nestedrecords, затемconsumerclosurea0b5dc иlive25.

## Арена: живой приём BattleSettings

### Что исследовано
6C после собственногоinventory, queuedexecution и returna0a834.
### Что доказано
Живой originalclient вернулся изBattleSettings,mode0/field40=1/owner1.
Сессия6s завершена; баланс10000/10000 в отдельнойБД, основная не использовалась.
### Новые packet mappings
Подтверждено live6C+BODY без дополнительного преобразования.
### Новые структуры
Нет; диагностическийпрофиль отдельно от productionroomstate.
### Изменённые файлы
 tools/run_reservation.py,tools/loopback_exchange.py,tools/capture_loaded_orange.py,
tests/test_reservation_launcher.py,evidence/battle_settings_live.log/summary,
ARENA.md,NEXT_TASK.md,WORK_REPORT.md.
### Добавленные тесты
Probeisolation/mainDB/roster/mutationcompatibility guards;114unittest PASS.
### Что остаётся неизвестным
Открытие комнаты, основнойBattleMemberList, успешныйcreatehandshake и полныйбой.
### Риски и альтернативы
ПриёмSettings не приравнивается созданнойкомнате; состояние сервера не менялось.
### Следующий самый полезный шаг
ОсновнойBattleMemberList/открытиеwindow_battleroom, затем servercreation.

## Арена: промежуточная очередь обработчиков

### Что исследовано
81d588 UI followup, liveac60e0 pointer, ti.exe71cc6c→6f6984.
### Что доказано
Live callback вti.exe совпадает сPEкодом; original callback копирует bodyбез изменений
и сохраняетa0a834 как обработчик. Native доqueue insertion PASS.
### Новые packet mappings
Уточнён путь6C; bodyне требует дополнительного преобразования до очереди.
### Новые структуры
Queue32bytes: callback+0c, bodypointer+1c. Остальное ещё не именуется.
### Изменённые файлы
 tools/capture_loaded_orange.py, tools/verify_arena_callback_queue.py,
evidence/arena_callback_live.log,arena_callback_target.json,arena_callback_queue_native.json,
arena_settings_followup.asm,ARENA.md,NEXT_TASK.md,WORK_REPORT.md.
### Добавленные тесты
Native ti.exe allocation/liststubs с originalcopy PASS; серверные алгоритмы не менялись.
### Что остаётся неизвестным
Исполнениеqueuedreader, live6C, открытие комнаты и полныйответ создания.
### Риски и альтернативы
Проверка копирования не доказывает успешное отображение. Диагностический запуск завершён.
### Следующий самый полезный шаг
Queued execution/live6C на отдельной сессии, BattleRoom и создание.

## Арена: параметры боя BattleSettings

### Что исследовано
Dispatcher a0b234, entrya0a834,69? нет:6C, wrapper68a850, followupa0ac58.
### Что доказано
6C регистрируетRECV_BattleSettings; bodylayout подтверждён original numericreader
в ветках0/16/21 до последнего поля с точнымcursor.
### Новые packet mappings
6C→68a850(callbacka0a834); внешнийwrapper ещё не проверен.
### Новые структуры
BattleSettings BODY codec сmode16extension. UNKNOWNvalues сохраняются.
### Изменённые файлы
protocol/arena.py,tests/test_arena.py,tools/verify_battle_settings_native.py,
evidence/battle_settings_native.json,arena_state_reader.asm,ARENA.md,NEXT_TASK.md,WORK_REPORT.md.
### Добавленные тесты
3nativebranches PASS; bodyfixtures/truncations/trailing;113unittest PASS.
### Что остаётся неизвестным
Externalwrapper,followup81d588, полноценный ответ создания и lifecycle.
### Риски и альтернативы
СостояниеBattleSettings не приравнивается успешному созданию; полный wireпакет не выдаётся.
### Следующий самый полезный шаг
68a850 externalcallback и81d588, затем подключение создания комнаты.

## Арена: запрос подтверждения создания боя

### Что исследовано
Constructor85ee10, кнопкаmn53,callback85d658, buildera0a6f4, serializer6468b4.
### Что доказано
C8/2B20bytes,9fields. Original setters/serializer/byte/u32writers исполнены.
Только packetbegin/end заменены. GUIисточники большинства параметров найдены.
### Новые packet mappings
C2SC8/2B create battle; точный порядок ARENA.md.
### Новые структуры
ArenaCreateRequest, unknownfields сохранены, две soldiercounts раздельны.
### Изменённые файлы
protocol/arena.py,tests/test_arena.py,tools/verify_arena_create_request_native.py,
evidence/arena_create_window.asm,arena_create_request_native.json,ARENA.md,NEXT_TASK.md,WORK_REPORT.md.
### Добавленные тесты
Original2cases PASS, independentwire roundtrip/alltruncations/trailing;112unittest PASS.
### Что остаётся неизвестным
Ответ создания, структура состояния боя, последнееu32, полноценный lifecycle.
### Риски и альтернативы
СтарыеBAзапросы не подменяют этот запрос. Codec не означает созданный бой.
### Следующий самый полезный шаг
Ответ/stateconsumer a0a83c и настройкиac6008, затем серверное создание.

## Арена: доказанная привязка кнопки создания

### Что исследовано
GUIconstructor87578c, mn53/mn18, Delphi interface table874cc8 и invoke thunks.
### Что доказано
«Создать» открываетwindow_servercreate через8737f4; это отдельный путь отBA03.
Native callback chain исполнялся до возврата с windowhelpers-stubs.
### Новые packet mappings
Нет; исправлена недоказанная гипотеза прямого соответствияBA03 кнопке создания.
### Новые структуры
UIinterface offset38→vtable874bf8→874969→87537c. ПодробностиARENA.md.
### Изменённые файлы
 tools/verify_arena_create_binding.py,evidence/arena_create_ui_binding.json,
evidence/arena_buttons.asm,ARENA.md,NEXT_TASK.md,WORK_REPORT.md.
### Добавленные тесты
Нативная проверка interface binding/callbackchain PASS, новый код сервера не менялся.
### Что остаётся неизвестным
Подтверждениеwindow_servercreate, смыслBA04второй таблицы, серверный lifecycle.
### Риски и альтернативы
Две таблицы имеют разные пути входа; объединять их протоколы нельзя.
### Следующий самый полезный шаг
Кнопка подтвержденияwindow_servercreate и связанные сac6008 настройки.

## Арена: выход и исключение участника

### Что исследовано
872430,87a0ac/87a0c0 и ms06 вrussian.lng.
### Что доказано
BA05 указывает characterID,flag0 для self leave,flag1 для kick выбранного игрока.
Original callbacks исполнялись целиком; отсутствие комнаты не отправляет пакет.
### Новые packet mappings
Уточнена семантикаBA05; ARENA.md и arena_remove_localization.json.
### Новые структуры
ArenaRemoveRequest(character_id,kick).
### Изменённые файлы
protocol/arena.py,tests/test_arena.py,tools/verify_arena_requests_native.py,
evidence/arena_requests_native.json,arena_remove_localization.json,ARENA.md,NEXT_TASK.md,WORK_REPORT.md.
### Добавленные тесты
3nativecallbackcases добавлены к6writers (9PASS).111unittest PASS.
### Что остаётся неизвестным
BA03/04создание и вход, владелец комнаты, связь состава; нет полного lifecycle.
### Риски и альтернативы
Codec не даёт разрешения на kick; нужна серверная проверка владельца комнаты.
Не изменять roster/wallet при исследовании этих запросов.
### Следующий самый полезный шаг
UIисточникBA04 иBA03, затем lifecycle с проверками membership/owner.

## Арена: состав комнаты и условие входа

### Что исследовано
85fe74 member record и8600d0 consumer, BA0B dispatcher.
### Что доказано
Own characterID присутствует→сохранениеroomID/in_room1; отсутствует→FFFFFFFF/0.
Full original consumer вернулся, cursor точный, поля всех3бойцов размещены правильно.
### Новые packet mappings
BA0B roomID/u8/count +members. ПодробностиARENA.md.
### Новые структуры
ArenaMember(characterID,name,unknowns,pets), ArenaMemberPet(3bytes,7ints,name).
### Изменённые файлы
protocol/arena.py, tests/test_arena.py, tools/verify_arena_members_native.py,
evidence/arena_member_reader.asm, arena_members_native.json, ARENA.md,NEXT_TASK.md,WORK_REPORT.md.
### Добавленные тесты
Native3fullconsumer cases PASS; codec independentwire/truncation/trailing/countlimits.
110unittest PASS.
### Что остаётся неизвестным
Поля бойцов, соответствие запросам создания/входа, liveUI и серверный lifecycle.
### Риски и альтернативы
Присутствие собственногоID — необходимый native gate, не доказательство игрового боя.
Chat/UI helpers изолированы; визуальное отображение не проверено.
### Следующий самый полезный шаг
СвязатьBA03/04/05 с memberlist и данными текущего персонажа для lifecycle.

## Арена: категория, число бойцов и полный формат комнаты

### Что исследовано
875118 callback,87969c counter,875570/8756a4 callers и связьac55a4→ac48a0.
### Что доказано
BA03 несёт категорию и count ненулевых состояний из31слота, не IDs выбранных бойцов.
Native callback/counter/writers исполнялись целиком на трёх составах.
### Новые packet mappings
УточнениеBA03:u8 category,u8 count(state!=0); назначение операции UNKNOWN.
### Новые структуры
ArenaRoom BA02; неизвестные поля сохранены с native offsets.
### Изменённые файлы
protocol/arena.py, protocol/city_services.py, tests/test_arena.py,
tools/verify_arena_roster_count_native.py, evidence/arena_roster_count_native.json,
ARENA.md, NEXT_TASK.md, WORK_REPORT.md.
### Добавленные тесты
3native callback cases PASS; codec сравнивается с независимым native fixture,
все усечения/лишние байты/negative count отклоняются.108unittest PASS.
### Что остаётся неизвестным
Названия категорий, смысл операцииBA03, ответы создания/входа, полноценная Арена.
### Риски и альтернативы
Счётчик состояния нельзя выдавать за выбранный состав; серверные переходы ещё не добавлены.
### Следующий самый полезный шаг
BA0B8600d0 member list и источники UIкатегорий, затем lifecycle комнаты.

## Арена: исходящие запросы и ответ списка

### Что исследовано
Builders85f890..85fa50 и callers из gui3_ArenaList, текущий city_service_reply.
### Что доказано
Шесть original builders с настоящими byte/u32 writers сформировали ожидаемые пакеты.
BA01 запрашивает список без параметров после очистки UI списка.
### Новые packet mappings
BA01→BA02(count0) подключён. BA03:u8,u8;BA04:u32;BA05:u32,u8;BA07/09:u8.
### Новые структуры
Нет новых доменных структур; семантика параметров остаётся UNKNOWN.
### Изменённые файлы
protocol/city_services.py, tests/test_city_services.py, tools/verify_arena_requests_native.py,
ARENA.md, NEXT_TASK.md, WORK_REPORT.md, evidence/arena_requests_native.json.
### Добавленные тесты
Native6 writers PASS, прежние Arena readers PASS, полный unittest106 PASS.
Router проверяет точную длину списка и не принимает неизвестные мутации.
### Что остаётся неизвестным
Создание/вход/подтверждение состава, значения полей и полноценный бой.
### Риски и альтернативы
Пустой список соответствует отсутствующим комнатам; это промежуточная реализация,
не завершённая Арена. UI end-to-end в этом шаге не проверен.
### Следующий самый полезный шаг
Callers87512f/875589/8756bd: подтвердить значенияBA03, затем серверный lifecycle.

## Арена: начало восстановления списка комнат

### Что исследовано
Штатный GUI через Sky и клиентский GUI3_PDA_ArenaClick/RECV_ArenaRoomList.
### Что доказано
Sky не вернул окно запущенногоTI; finite90s завершён, UI actions не делались.
Original BA/02 dispatcher принимает пустой список; parser непустой записи читает
все поля до фильтрации. Numeric readers настоящие, allocation/strings/UI stubbed.
### Новые packet mappings
BA/02→860282→85fcc8→85fa88, signed i16 count. Подробности ARENA.md.
### Новые структуры
Запись комнаты: четыреu32, восемьu8, CString; неизвестные значения не переименованы.
### Изменённые файлы
ARENA.md, NEXT_TASK.md, WORK_REPORT.md, tools/verify_arena_room_native.py,
evidence/arena_room_reader.asm, arena_room_native.json, city_ui_roster_live.log.
### Добавленные тесты
Native: пустой dispatcher до возврата и непустой parser до фильтрации PASS.
### Что остаётся неизвестным
Исходящий запрос, семантика полей, lifecycle комнат, подтверждение выбора отряда.
### Риски и альтернативы
Непустой список ещё не проверен до UI; подключать выдуманные комнаты преждевременно.
### Следующий самый полезный шаг
Проследить93fe70 и исходящий запрос списка, восстановить создание/вход в комнату.

## Отряд при стандартном запуске города

### Что исследовано
Путь run_reservation.py → loopback_exchange.py и флаги включения городских транзакций.
### Что доказано
CONFIRMED: стандартный запуск прежде исключал отряд; теперь live без специального флага
обработал actor1/resource1/HP100, inventory1001/template301, wallet10000/10000.
Доказательства: evidence/default_roster_live.log и default_roster_live_summary.json.
### Новые packet mappings
Нет: применяются ранее подтверждённые66,30,C8/39.
### Новые структуры
Нет.
### Изменённые файлы
 tools/run_reservation.py, tests/test_reservation_launcher.py, README.md, NEXT_TASK.md,
CITY_FUNCTIONALITY_AUDIT.md, WORK_REPORT.md и новые live evidence.
### Добавленные тесты
Три проверки launcher: отряд без автоматических покупок/найма, явный empty-roster,
запрет mutation probes в основной БД. Полный unittest:105 PASS.
### Что остаётся неизвестным
UI выбор отряда и переход в бой, снаряжение, полный ассортимент и остальные функции города.
### Риски и альтернативы
Стартовый actor — локальный экспериментальный профиль. Вход всё ещё инструментирован.
--empty-roster позволяет диагностировать прежнюю пустую сессию; данные SQLite сохраняются.
Live завершён по заданному таймеру6s; это не доказательство длительной стабильности.
### Следующий самый полезный шаг
Проверить штатные кнопки с загруженным отрядом и восстановить подготовку Арены.

# Увольнение наёмника — 2026-09-12

## Что исследовано
UI8a2558 выбирает petID+28 и вызывает writer8c3c64. Consumer8c40d4
читает ID, уничтожает объект и обнуляет слот; это S2C65.
## Что доказано
Native запрос6402000000 удалил нанятогоpet2; handler65 вернулся с roster[1].
SQLite сохранил толькоpet1, баланс9900/10000 не изменился. История найма
сохранена, поэтому удалённый ID не переиспользуется. См.dismiss_live_summary.json.
## Новые packet mappings
C2S64,u32petID; S2C65,u32petID. После удаления отправляется актуальный
inventory30 оставшихся бойцов, чтобы обновить UI и снять ожидание.
## Новые структуры
HireStore.dismiss с BEGIN IMMEDIATE. Только принадлежащие аккаунту
нанятые бойцы и пустой inventory. Стартовый актор сохраняется (локальная политика).
## Изменённые файлы
hire.py, hiring.py, loopback_exchange.py, capture_loaded_orange.py,
run_reservation.py, tests/test_hire.py, tests/test_hiring.py.
## Добавленные тесты
102unit tests PASS. Чужой ID, стартовый актор, непустой инвентарь,
повторный запрос, сохранение денег и новый ID после следующего найма.
Live6сек в отдельной базе завершён.
## Что остаётся неизвестным
Кнопка увольнения через UI не проверена. Отказы используют generic394,
визуальное отображение которого пока не доказано. Обычный запуск
всё ещё требует включения собственного отряда из диагностического режима.
## Риски и альтернативы
Без возврата цены найма; кандидаты после увольнения не появляются заново
в локальном каталоге. Экипировка/боевое состояние ещё не реализованы,
при их добавлении нужны дополнительные ограничения увольнения.
## Следующий самый полезный шаг
Переход к штатному отряду и интерфейсу, подготовка арены. Все функции
города остаются целью, текущие проверки не означают её завершения.

# Найм кандидата — 2026-09-12

## Что исследовано
GUI_CreatePetShopWindow:8ac118 локализацияm248=Цена, колонка7(+1c).
8aae9c заполняет её полемebp-1c, соответствующим record+194 и последнемуu32.
## Что доказано
Цена найдена. Локальный каталог задаёт100cr. Native запрос6302000000
нанялcandidate2: созданpet2/resource2, баланс10000->9900. Повторный вход
принял обоих бойцов и9900/10000. См.evidence/hiring_live_summary.json.
## Новые packet mappings
ОбработанC2S63; ответы66,30,C8/39,62 с оставшимися кандидатами.
Запрос61 теперь исключает уже нанятых кандидатов данного аккаунта.
## Новые структуры
HireStore; hired_candidates(account,candidate_id,pet_id). INSERT бойца,
списание и отметка кандидата атомарны. Повторный найм отклоняется.
Максимум31 слот соответствует размеру клиентского массива. Старые hiredID
не переиспользуются. Цена доступна как HireCandidate.price_credits.
## Изменённые файлы
hiring.py, city_catalogs.py, loopback_exchange.py, config/city_catalogs.json,
capture_loaded_orange.py, run_reservation.py, tests/test_hiring.py.
## Добавленные тесты
101unit tests PASS: найм, изоляция, повторный запрос, нехватка денег,
rollback при ошибке записи кошелька. Live8сек найм и6сек повторный вход
завершены; оригинальный клиент принял resource2 с ненулевымresource_pointer.
## Что остаётся неизвестным
Кнопка найма через UI не проверена; обычный отряд пока в --probe-owned-pet.
Отказ лимита/повторного найма использует generic394, отображение которого
ещё не подтверждено. Арена, увольнение и другие функции города не готовы.
## Риски и альтернативы
Только два локальных человеческих кандидата. Не выдавать локальные100cr
за историческую цену. Фабрика явно требует10.0stats,100HP и нулевую
внешность текущегоfixture; иные параметры отклоняет вместо молчаливой подмены.
Основные пользовательские10000/10000 не тратились.
## Следующий самый полезный шаг
Проверить штатный интерфейс и включить собственный отряд в обычный запуск;
дальше увольнение и подготовка арены. Общая цель остаётся активной.

# Тип кандидата и запрос найма — 2026-09-12

## Что исследовано
Reader62:8c3e7d/8c3e8c, UI8aab9c копирует запись вebp-1b0;
поля+100/+104 затем становятсяebp-b0/ebp-ac. Выбор строки8ab99a.
## Что доказано
Первоеu32 — ID кандидата, колонка0, преобразуется424724 в запрос63.
Второеu32 — тип: преобразуется в pe0N и локализуется. В russian.lng
pe01=Мужчина,pe02=Женщина. Значение100 в исходном локальномfixture
было неверным типом, не ценой; заменено на1/2. Деньги не списывались.
## Новые packet mappings
C2S63,u32candidateID; codec подтверждён двумя запусками native writer8c3c34.
## Новые структуры
HireCandidate.candidate_id/resource_type — семантические свойства без
ломающего переименования wire fields. Кодек hire.py.
## Изменённые файлы
config/city_catalogs.json, city_catalogs.py, hire.py,
verify_hire_request_native.py, tests/test_hire.py и документация.
## Добавленные тесты
99unit tests PASS;2 native writer cases PASS; native catalog readers PASS.
## Что остаётся неизвестным
Цена найма. Последнееu32 попадает в запись+194 и UI колонку7;
это ещё не доказательство цены. Серверная операция63 пока не подключена.
## Риски и альтернативы
Не списывать второеu32 как цену — оно является типом бойца.
Остальные параметры кандидатов локальныеfixtures; настоящие статы
и соответствие собственного actor должны быть проверены.
## Следующий самый полезный шаг
Проследить UI колонку7/последнееu32: подтвердить цену, затем атомарный
найм и отправка66/30/C8/39. Поддержка всего отряда уже готова.
Общая цель всех городских функций остаётся активной.

# Загрузка всего собственного отряда — 2026-09-12

## Что исследовано
C2S63 builder8c3c34, UI call8ab9ae; сохранение owned_pets и обработка2F.
Предыдущий цикл был прогрессом: обработка отказа магазина принята live.
## Что доказано
Сервер был ограничен одним бойцом; теперь загружает весь сохранённый
отряд текущего аккаунта и читает актуальный инвентарь каждого из SQLite.
Live6сек создалslot0/id1 иslot1/id2; клиент запросил оба inventory и получил
два корректных ответа30. См.evidence/roster_two_live_summary.json.
## Новые packet mappings
Новых wire форматов нет; C2S63 подтверждён как одинu32 из выбранной строки UI.
Полная семантика/цена кандидата ещё требует проверки до списания.
## Новые структуры
OwnedPetStore.list(account), inventory(account,owner). Проверяются соответствие
ключа ID данным и сохранённые wire snapshots; запрос чужого бойца даётNone.
## Изменённые файлы
owned_pets.py, loopback_exchange.py, test_owned_pets.py и документация.
## Добавленные тесты
Два бойца, стабильный порядок, изоляция аккаунтов и разные inventory;
97unit tests PASS. Live в отдельной тестовой базе завершён по таймеру.
## Что остаётся неизвестным
Покупка кандидата63 ещё не реализована: нужно подтвердить цену/тип и
поля собственного бойца. Два тестовых бойца были внесены в отдельную базу,
их появление не является доказательством работы кнопки найма.
## Риски и альтернативы
Собственный отряд пока включается флагом --probe-owned-pet. Необходим
переход к обычному отряду после проверки UI и стартовых данных.
## Следующий самый полезный шаг
Найм63: подтвердить цену кандидата, атомарно сохранить нового бойца и
списать средства; повторный вход теперь уже поддерживает весь отряд.
Общая цель функций города остаётся активной, арена ещё не готова.

# Отказы магазина — 2026-09-12

## Что исследовано
F0 typed arguments7d09xx, command47 branch7d2d12, generic394,
очистка ожидания7d1d91/9dc760; локализацияsm47/s394.
## Что доказано
47 требует числовой templateID, а не текст: native424724 преобразует
аргумент в число, a75f24 ищет название предмета. Отправка1(type1) даёт
реальный вывод «Не хватает Credits.» и возврат обработчика. Строковая
гипотеза47 была опровергнута исключением и удалена до завершения работы.
## Новые packet mappings
F0/47,count1,type1,value1 — недостаточно кредитов. F0/394,count1,type0,
CString — ошибка параметра; ветвь не вызывает специальных действий.
## Новые структуры
shop_errors.py переводит известные отказы в ответы клиента, неизвестные
внутренние тексты заменяет общей причиной. UTF-8 Python/CP1251 CString.
## Изменённые файлы
system_message.py, shop_errors.py, loopback_exchange.py,
capture_loaded_orange.py, build_item_fixture.py и tests/test_shop_errors.py.
Каталог теперь включает исходные записи валют1/2 плюс прежние4 предмета.
## Добавленные тесты
96unit tests PASS. verify_shop_errors_native.py подтвердил reset1->0
и numeric parse47. Live6сек: вывод сообщения, возврат обработчика,
неизменные0credits/10000gold и один предмет в отдельной тестовой базе.
## Что остаётся неизвестным
Экранные пиксели сообщения не проверены: наблюдали вызов вывода текста.
Для generic394 в первом live обработчик вернулся, но отображение не
подтверждено. Остальные отказы нужно проверять по отдельности.
## Риски и альтернативы
Названия валют пока английские Credits/Gold из исходного items.cfg.
Основной пользовательский баланс не изменяли. Не трактовать отсутствие
списания или96tests как готовность всех городских функций.
## Следующий самый полезный шаг
Восстановить найм и полноценный собственный отряд, проверить штатный UI
магазина и арены. Общая цель всех функций города активна; отдельный пункт
«Сервисы» по просьбе пользователя пока отложен.

# Продажа предметов — 2026-09-12

## Что исследовано
Цепочка продажи:8a0fe4 запрос цены,8a15a0 RECV_ItemPrice,
подтверждениеa65e88 вызывает99034c. h1_5/m246 из russian.lng.
## Что доказано
B806 запрашивает цену поowner/instance/quantity, B807 возвращает дваu32,
первый отбрасывается, второй отображается как цена. Подтверждение отправляет
23+owner+instance+quantity. Реальный клиент через native builder продал
нож1002: inventory2->1, credits9900->9965, gold10000. SQLite сохранил результат.
## Новые packet mappings
C2S B806 price query; S2C B807 price quote; C2S23 sale commit.
## Новые структуры
ShopSale codec и ShopStore.sell(quote=True/False). Quote не меняет деньги
или предметы. Продажа атомарна и заново проверяет наличие/владение.
item_sequences исключает повторное использование удалённых ID.
## Изменённые файлы
shop_sale.py, shop.py, loopback_exchange.py, capture_loaded_orange.py,
run_reservation.py, test_shop.py, verify_shop_sale_native.py и документация.
## Добавленные тесты
Quote без изменения, продажа, повторная продажа, неверный получатель,
rollback при отказе записи и защита от старого ID после новой покупки.
93unit tests PASS;2 original sale builder cases PASS; numeric prefix
оригинального quote reader прочитал8bytes/65credits. Live завершён6сек.
## Что остаётся неизвестным
Штатное перетаскивание на кнопку продажи и подтверждение UI не проверены.
Отказы пока логируются, сообщения клиенту ещё не восстановлены.
Амортизация, модификаторы, надетые вещи, стаки не поддержаны.
## Риски и альтернативы
Поддержаны лишь нетронутые fixtures301/326; цена65% локальной цены магазина
по клиентской справке, целочисленное округление вниз — локальная политика.
Сама продажа не требует предварительного quote: цена всегда серверная.
Live работал с отдельной тестовой базой; основные10000/10000 не тратили.
## Следующий самый полезный шаг
Собственный отряд/инвентарь в обычном запуске и штатный UI магазина;
затем найм и арена. Все функции города остаются целью, отдельное меню
«Сервисы» отложено. Не считать packet-level работу полной готовностью UI.

# Покупка обычного магазина — 2026-09-12

## Что исследовано
Запрос75 соединён с каталогом, кошельком и сохранённым inventory30.
Предыдущий цикл дал реальный прогресс: кошелёк C8/39 принят клиентом.
## Что доказано
Оригинальный builder9919c8 отправил покупку одного ножа offer2 дляowner1.
Сервер списал100 кредитов; оригинальные consumers приняли9900/10000 и
inventory с instance1002/template326. Повторный вход из той же отдельной
тестовой базы принял те же деньги и оба предмета. См.evidence/shop_purchase_live_summary.json.
## Новые packet mappings
Нет новых opcode. Реализован обработчик75 с обновлениями30 и C8/39.
## Новые структуры
ShopStore/PurchaseResult/PurchaseRejected; BEGIN IMMEDIATE объединяет
списание и записьinventory, проверяет аккаунт, получателя, offer, сумму,
количество и размер сериализованного списка. ID уникальны между бойцами аккаунта.
## Изменённые файлы
Добавлены tio/shop.py и tests/test_shop.py; изменены loopback_exchange.py,
run_reservation.py, capture_loaded_orange.py и описания хранения/каталога.
## Добавленные тесты
Покупка и сохранение, неверные запросы, rollback при ошибке записи,
два конкурирующих запроса без перерасхода. Все90 unit tests PASS.
Два конечных live запуска: покупка8сек и повторный вход6сек, завершены.
## Что остаётся неизвестным
Клик через штатный UI ещё не проверен; ownerID в реальном UI остаётся
STRONG. Отказ логируется, пользовательское сообщение/закрытие ожидания
не реализованы. Продажа, найм, арена и другие городские функции не готовы.
## Риски и альтернативы
Покупка работает пока в --probe-owned-pet и с базой. Только подтверждённые
локальные fixtures Beretta301/Knife326; цены локальные, quantity1..1000,
остатки магазина пока не ограничены (назначение unknown02 не установлено).
Диагностический --probe-purchase требует отдельную базу и --probe-owned-pet.
Дедупликация одинаковых запросов75 не вводится без transactionID в протоколе.
Основной баланс пользователя10000/10000 в проверках не тратили.
## Следующий самый полезный шаг
Проверить штатный UI магазина и обработку отказа; затем продажа и найм.
Подготовить собственный отряд для обычного запуска, не оставлять его
навсегда в диагностическом режиме. Общая цель всех функций города активна;
отдельное меню «Сервисы» пока отложено по просьбе пользователя.

# Баланс и уточнение объёма работ — 2026-09-12

Пользователь уточнил: восстановить все функции города (арена, найм,
магазин, инвентарь и прочее); отдельное меню «Сервисы» пока отложено.
Стартовый баланс по прямому запросу: 10000 кредитов и 10000 золота.

## Что исследовано
RTTI TGlobalCharater и потребитель7d4c28 RECV_AssetCount; таблица
маршрутизации65d392, reader65802c, регистрацияab8760.
## Что доказано
Кредиты записываются в character+230, золото в+234. Wire C8/39:
внутренний идентификатор56 не является wire opcode. Первый live опыт
без правильной маршрутизации не вызвал consumer; исправленный C8/39
вызвал его и сохранил10000/10000. Полный лог последнего опыта и summary
находятся в evidence/wallet_starting_live*. UI визуально не проверялся.
## Новые packet mappings
S2C C8/39 AssetCount:10u32, optional flag, при наличии u64+u32.
## Новые структуры
AssetCount codec с сохранением неизвестных полей; SQLite wallets
(account,credits,gold). ensure создаёт баланс один раз, не сбрасывает его.
## Изменённые файлы
asset_count.py, wallets.py, loopback_exchange.py, capture_loaded_orange.py,
verify_asset_count_native.py, test_wallets.py и документация.
## Добавленные тесты
Начальный баланс, повторное открытие без сброса, изоляция аккаунтов,
строгий разбор пакета. 86 unit tests PASS. Оригинальные reader и consumer
проверены на2 наборах с явными UI stubs. Live6 секунд:10000/10000,
Reservation background и inventory instance1001/template301 приняты.
## Что остаётся неизвестным
Семантика двух дополнительных счётчиков и optional блока; визуальное
отображение баланса ещё не проверено. Покупка75 пока не обрабатывается.
## Риски и альтернативы
Диагностический вход инструментирован, это не доказательство обычного
входа или готовности всех функций. Остальные счётчики пока локальные0.
## Следующий самый полезный шаг
Атомарная покупка75: проверка предложения, получателя и количества,
списание сохранённых кредитов, новый inventory30 и баланс C8/39.
После этого найм и арена. Отдельное меню «Сервисы» не является приоритетом.

# 2026-09-12 — запрос покупки и источник цены

## Что исследовано
Builder9919c8, UI9762b7/9764d9, локализацияm1261, owner UI9ac64c.

## Что доказано
75:u32,u8,u32,u32; IDoffer из+30; количество из поля ввода;
ценаcr из+40. Globalac60d4 — ранг отряда, ac599c — множитель кредитов,
не денежный баланс. Это исключает некорректное списание этих полей.

## Новые packet mappings
C2S75 ShopPurchase. Серверный результат покупки пока не реализован.

## Новые структуры
ShopPurchase(owner_id,category,offer_id,quantity). owner_id пока STRONG,
остальные перечисленные связи подтверждены writer/UI. Zeroquantity сохраняется
codec для явного отклонения на уровне транзакции.

## Изменённые файлы
shop_purchase.py,verify_shop_purchase_native.py,test_shop_purchase.py,
SHOP_PURCHASE.md,NEXT_TASK.md и записи evidence.

## Добавленные тесты
84unit PASS;2original builder cases PASS, точное совпадение14bytes.

## Что остаётся неизвестным
Источник кошелька, изменения после покупки и отказы; покупки не подключены.

## Риски и альтернативы
Не списывать ранг/множитель кредитов. Не путать OfferID с templateID.
Проверить связь Credits1/Gold2 с реальным балансом, не предполагать её.

## Следующий самый полезный шаг
Доказать путь денежных данных; затем атомарная транзакция покупки,
обновление inventory и визуальная проверка. Полная цель не завершена.

---

# 2026-09-12 — непустой inventory и сохранение собственного бойца

## Что исследовано
Original item reader63bd38, consumer990638, primitive readers65fef4/ff04/ff14.
Текущий собственный actor probe и сохранение SQLite.

## Что доказано
35-byte record при отсутствующих optional;39bytes с optional-u32.
Live: inventory содержит один instance1001/template301.

## Новые packet mappings
Расширен30 с пустой ветки на обычные item records; новые opcodes не добавлены.

## Новые структуры
ItemRecord с неизвестными byte/word полями; optional-u32 поддержан,
строковый и вложенный блоки явно отклоняются. OwnedPetStore wire snapshots.

## Изменённые файлы
item_list.py,owned_pets.py,loopback_exchange.py,capture_loaded_orange.py,
verify_item_record_native.py,test_item_list.py,test_owned_pets.py,
INVENTORY.md,NEXT_TASK.md и trial evidence.

## Добавленные тесты
82unit PASS: запись/повторное открытие БД, запрет seed reset, account isolation,
несовпадение owner, item roundtrip и усечения. Original item decoder3cases PASS.
Live непустой inventory, сохранение и отдельная проверка повторного входа.

## Что остаётся неизвестным
Транзакции найма/покупки/продажи, кошелёк, полная игровая семантика полей,
визуальное использование предмета и остальные городские сервисы.

## Риски и альтернативы
Запуск по-прежнему opt-in --probe-owned-pet. Не включать фиктивное
списание денег или считать сохранение snapshot реализацией покупки.

## Следующий самый полезный шаг
Разобрать городские операции и кошелёк, проверить UI; затем интегрировать
настоящие транзакции поверх сохранения. Полная цель остаётся активной.

---

# 2026-09-12 — живой собственный боец и пустой инвентарь

## Что исследовано
Ресурсный lookupa853cc, live PetInfo, возникший после него2F,
writers99002f/63ce70, decoder63ce00, consumer990638.

## Что доказано
Два live запуска создали slot0/id1/resource1 с ненулевым resource pointer.
PetInfo reader вернулся. Без30 запрос2F повторился5раз за8s; с30 — один
запрос и один ответ, повторов за оставшийся интервал нет.

## Новые packet mappings
Bare C2S2F:u16count/u32IDs; S2C30:u32owner,u8unknown,u32count/items.
C8/2F обнаружен как отдельный формат, не используется для bare2F.

## Новые структуры
Проверен пустой ItemList30. Непустой record63bd38 ещё не восстановлен.

## Изменённые файлы
item_list.py, verify_empty_item_list_native.py,test_item_list.py;
loopback_exchange.py,capture_loaded_orange.py,run_reservation.py;
INVENTORY.md,PET_INFO.md,NEXT_TASK.md; trial и сводка live evidence.

## Добавленные тесты
80unit PASS. Дваoriginal decoder cases PASS без stubs.
Два live запуска по8s; оба завершились диагностическим таймером.

## Что остаётся неизвестным
Полная игровая семантика trial значений и визуальное отображение бойца.
Непустой inventory, сохранение, покупки/найм, остальные сервисы не готовы.

## Риски и альтернативы
Trial только opt-in --probe-owned-pet. Не стирать реальный inventory пустым
ответом. Исключения распаковщика до login не смешивать с результатом66.

## Следующий самый полезный шаг
Разобрать item record, заполнить inventory из сохранённого состояния;
затем покупки/найм. Полная цель городских функций остаётся активной.

---

# 2026-09-12 — codec PetInfo66 и ветки собственного бойца

## Что исследовано
Текущая трасса reader8c4380, новый/существующий слот, внешность,
ветки equipment13/3 и дополнительные данные основного персонажа.

## Что доказано
Восемь сочетаний профиля успешно прочитаны оригинальным reader.
Пакет от codec с непустым именем прочитан до конца; новый слот получаетID.
Конструктор модели и managed-string conversion заглушены явно — это не live/UI.

## Новые packet mappings
Нет новых opcodes; расширена доказательная база PetInfo66.

## Новые структуры
PetInfo с полями по callsite, выбором профиля и строгим совпадением полей.
Внешность добавляет6bytes, owner block20bytes, equipment различается на20bytes.

## Изменённые файлы
tio/protocol/pet_info.py, tools/trace_pet_info_native.py,
tools/verify_pet_info_native.py, tests/test_pet_info.py, PET_INFO.md,NEXT_TASK.md.

## Добавленные тесты
78unit PASS. Усечения на каждом байте, лишние данные, неверные профили,
неподдержанные timed/trailing states. Eight original-reader profiles PASS.

## Что остаётся неизвестным
Полная семантика полей; создание валидного живого actor с моделью,
сохранение и найм; timed states и trailing string ещё не поддержаны.

## Риски и альтернативы
Не выдавать нулевую структурную fixture за игрового бойца.
Кодек пока не отправляется из production session, чтобы не создавать
бойцов с неподтверждёнными значениями. Это следующий необходимый шаг проверки.

## Следующий самый полезный шаг
Связать поля с моделью/здоровьем/уровнем и проверить live PetInfo для бойца.
Затем сохранение owned roster и операция найма. Полная городская цель активна.

---

# 2026-09-12 — PetInfo и аудит всех городских функций

## Что исследовано
Текущий код каталогов, handlers8c4380/8c40d4, builders8c3c34/8c3c64,
вложенный reader6d01f8, ресурсная веткаa93f9c. Computer Use: список окон
сейчас не содержит TI; действия с чужими окнами не выполнялись.

## Что доказано
65 удаляет бойца;66 находит/создаёт слот. Original PetInfo base reader
прочёл71поле/206bytes при явно заданных ограничениях трассы.

## Новые packet mappings
C2S63/u32,64/u32; S2C65/u32 PetDelete; S2C66 PetInfo.
63/64 ещё требуют связи с конкретными UI действиями.

## Новые структуры
PetInfo:ID,resource,CString,состояния,optional appearance6,
resource-dependent equipment13/3words,16floatbits и условные блоки.
Полная покадровая карта чтения сохранена в native trace JSON.

## Изменённые файлы
trace_pet_info_native.py,PET_INFO.md,CITY_FUNCTIONALITY_AUDIT.md,NEXT_TASK.md,
evidence/pet_info_reader.asm и pet_info_native_read_trace.json.

## Добавленные тесты
Новый воспроизводимый original-reader trace с проверкой полного потребления
206байт и остановки на выходе ветки. Первый запуск выявил незаглушенный
model calla86df8; после явного добавления model stub проверка прошла.

## Что остаётся неизвестным
Валидный полный actor, новые слоты, все optional ветки, значения состояния,
найм и прочие городские операции. Полная цель не выполнена.

## Риски и альтернативы
Нельзя отправлять структурную нулевую fixture как живого бойца; нельзя
объявлять65success найма. Аудит охватывает цель, но UI-инвентаризация неполна.

## Следующий самый полезный шаг
Расширить native trace на остальные ветки и вывести codec66 для owned roster.

---

# 2026-09-12 — каталоги магазина, рынка найма и услуг

## Что исследовано
Оригинальные dispatcher8c7edc/9929f4/84e420, readers8c3e2c/991b34/84e320,
writers61/69/B102, items.cfg и services.cfg. AZT не использовался.

## Что доказано
CONFIRMED: полный wire трёх списков; original readers потребляют все байты.
Live: ответы для69/61/B102 приняты, все три reader вернулись без script errors.
Отображение строк и работа транзакций этим не доказаны.

## Новые packet mappings
61→62 PetShopList;69category→74 ItemShopList;B102→B103 ServiceShopList.

## Новые структуры
ShopItem17bytes, HireCandidate с CString/optional6/16floatbits/tail,
ServiceOffer с вложенными13-byte options. Unknown поля сохранены без выдуманных названий.

## Изменённые файлы
tio/protocol/city_catalogs.py,city_services.py,tio/city_catalogs.py;
config/city_catalogs.json; loopback_exchange.py; build_item_fixture.py;
capture_loaded_orange.py и run_reservation.py (--probe-catalogs).
CITY_SERVICES.md,NEXT_TASK.md и актуальные указатели в документации.

## Добавленные тесты
76 unit PASS: маршрутизация, повторы, неизвестные запросы, оба optional branch,
float bits, усечения по каждому байту, trailing bytes, некорректные поля.
verify_city_catalogs_native.py:4 cases PASS, числовые поля и dispatch.
Два live запуска, второй с native request builders для61/B102.

## Что остаётся неизвестным
Семантика отдельных полей, исторические цены, owned roster, транзакции найма,
магазина и услуг. Услуги пока пусты; кандидаты тестовые, предметы с частичным CFG.

## Риски и альтернативы
Не подменять владение бойцом кандидатом рынка. Числа локальной fixture не
объявлять оригинальным балансом. Модель/боевые поля каталога ещё неполные.

## Следующий самый полезный шаг
Восстановить owned PetInfo и ответ на найм, затем атомарное сохранение в SQLite.

---

# 2026-09-12 — видимый Reservation и устранение автоматического закрытия

## Что исследовано
Три пользовательских снимка, последние loopback-журналы, жизненный цикл запускателя.

## Что доказано
CONFIRMED: Reservation виден, окна наёмников и premium открываются.
Последняя городская сессия094856793390Z завершена таймером45s; старый launcher
затем убивал свой клиент. Соответствие снимков этой сессии не установлено.
Новый live запуск с --seconds3 прошёл городской обмен и штатный таймер.

## Новые packet mappings
Нет. Существующий70→9E сохраняется в неограниченной сессии.

## Новые структуры
Нет. Добавлены события city_session_started/client_disconnected/session_stopped.

## Изменённые файлы
run_reservation.py: по умолчанию --seconds0, без таймера.
loopback_exchange.py: наблюдение до EOF/stop, короткие ожидания, остановка сокетов.
capture_loaded_orange.py: остановка exchange до ожидания в finally.
Актуализированы аудит, следующие шаги, документация; сохранены снимки с SHA256.

## Добавленные тесты
test_city_session.py: простой и ping без таймера, EOF, явный stop,
конечный таймер, проверка диапазона. Всего71 тест PASS.
Live: evidence/reservation_session_lifecycle_probe.log, --seconds3, штатный выход.

## Что остаётся неизвестным
Причина каждой отдельной неуспешной попытки; длительное использование без таймера.
Содержимое городских сервисов и обычный вход без инструментированных callbacks.

## Риски и альтернативы
Не выдавать пустой список и цены999999 за восстановленные данные.
Не считать таймер доказательством отсутствия любых иных аварий клиента.

## Следующий самый полезный шаг
Восстановить данные списка наёмников по оригинальному протоколу.

---

# Рабочий цикл — аудит завершения и доступности UI

## Что исследовано
Сопоставлены требования входа с актуальными live evidence и хранилищем.
Прочитаны исходное задание и поддерживаемый API выбора окон.

## Что доказано
Сетевой сценарий и повторный вход подтверждены, но видимое взаимодействие
не подтверждено. Shell работает в WinSta0/Default, не на отдельном desktop.

## Новые packet mappings
Нет.

## Новые структуры
Нет.

## Изменённые файлы
COMPLETION_AUDIT.md, NEXT_TASK.md, WORK_REPORT.md.

## Добавленные тесты
Новых тестов нет. Использованы ранее проверенные live результаты;
код не менялся, повторный запуск без новых условий не нужен.

## Что остаётся неизвестным
Видимый городской экран и обычный ввод через интерфейс TI.

## Риски / альтернативные интерпретации
Успешный renderer не равен доказательству видимости и взаимодействия.
Вопрос пользователю остаётся без ответа третий последовательный цикл.

## Следующий самый полезный шаг
Дождаться наблюдения пользователя или изменения доступности окна.
Инструмент get_goal вернул status=paused. Статус не изменялся; цель не завершена.

---
# Рабочий цикл — повторный вход сохранённого персонажа

## Что исследовано
Хранилище использовалось только внутри уникального каталога каждой пробы,
поэтому очередной запуск всегда начинался с создания персонажа.

## Что доказано
Два последовательных запуска оригинального клиента с одной базой:
первый создал персонажа, второй получил сохранённую запись без C2S11.
Оба выбрали персонажа и отрисовали Reservation. В SQLite осталась одна запись.

## Новые packet mappings
Нет. Использованы существующие10/17/18/19/1A и команды города98/117.

## Новые структуры
Настраиваемый database path. Начальный список персонажей и MyCharInfo
берут имя/ID из хранилища. Создание выполняется только при пустом списке.

## Изменённые файлы
loopback_exchange.py, capture_loaded_orange.py, run_reservation.py,
.gitignore (локальная data/), RESERVATION.md, NEXT_TASK.md, evidence.

## Добавленные тесты
67 unit tests PASS. Два live входа; машинная проверка create-count1→0,
loaded-count0→1, character-select и Reservation-render в обоих запусках.
Результат: persistent_reentry_summary.json.

## Что остаётся неизвестным
Визуальное подтверждение окна Reservation и обычный вход без
инструментированных login/selection callbacks. Остальные сервисные ответы.

## Риски / альтернативные интерпретации
Постоянное хранилище относится пока к диагностическому аккаунту probe_user.
Полные игровые правила и работа городских сервисов этим не доказаны.

## Следующий самый полезный шаг
Проверить видимый интерфейс Reservation; продолжить обычный сценарий входа.
Вопрос о визуальном результате остаётся без ответа, цель активна.

---
# Рабочий цикл — связь в городе и длительность проверки

## Что исследовано
Повторяющийся70, writer6d4b03, dispatcher6d4c08 и parser6d4b44.
Статические отправители69,b8,c5 найдены; ответы ещёнеугаданы.

## Что доказано
70 ожидает9E безpayload. Live клиент установил received1 и обновил elapsed;
Reservation продолжилотрисовку. Низкоуровневыйwriterhook нарушалB902,
послеудаленияперехвата рабочийвходвосстановлен.

## Новые packet mappings
CONFIRMED C2S70→S2C9E. Другимзапросам фиктивныеответы не отправляются.

## Новые структуры
city_service_reply с точнойвалидациейping; неизвестныепакетывозвращаютNone.

## Изменённые файлы
city_services.py/tests,loopbackservice routing,capturepingobservations,
run_reservation --seconds (1..3600),observationdeadline/join,
RESERVATION,NEXT_TASK,evidence/ping_reply_dispatch.asm.

## Добавленные тесты
67 unit PASS;extended180s завершён штатно, принятыхping replies: 17.
Reservationrender подтверждён, script errors0.

## Что остаётся неизвестным
ВизуальноеподтверждениеReservation,обычныйнеinstrumentedвход,
остальныегородскиесервисы. Пользователюзаданвопрос о видимомэкране.

## Риски / альтернативные интерпретации
Двараннихсбоябылидиагностическимвмешательством675bf8;hookудалён.
Не считать прохождениеping доказательством всехсервисовиливсейцели.

## Следующий самый полезный шаг
Получить/проверить визуальныйрезультат,дождатьсязавершенияowned180sprobe,
продолжить обычныйсценарийвхода. Цельостаётсяactive.

---
# Рабочий цикл — открытие Reservation сервернойкомандой117

## Что исследовано
Все прямыевызовы8596e0; найден F0branch7d26e2 и mappingcommand117.

## Что доказано
Live безtown-view-probe: F0117 вызвал штатноеоткрытие,render-loop загрузил
pda/loc_reserve.jpg,id3,loaded1. Повторный run_reservation.py подтвердил.

## Новые packet mappings
F0/u32command117/u32count0. ДополнительныегородскиеC2S5003,6900,b804,b811,
c501,70 зарегистрированы,ихответы покаUNKNOWN.

## Новые структуры
encode_open_town_view() вsystem_message.py,безаргументов.

## Изменённые файлы
Codec/test,loopback open-town-probe,capture observationalhook,
run_reservation.py,RESERVATION,NEXT_TASK,доказательстваbinarymapping/live.

## Добавленные тесты
65 unit PASS;два live server-driven открытияReservation;originalPE mapping
117→27→7d26e2 сSHAguard записанвevidence.

## Что остаётся неизвестным
Городскиесервисныеответы,визуальнаяпроверкаокна,обычныйпостоянныйзапуск.

## Риски / альтернативные интерпретации
Прямойtown-viewcallback исключён,но login/selection вresearchprobe ещё
instrumented. Runner ограничен45s и не являетсяготовымпостояннымсервером.

## Следующий самый полезный шаг
Визуально/интерактивнопроверитьReservation,восстановитьгородскиесервисы
и обычныйсценарийвхода. Цельостаётсяactive.

---
# Рабочий цикл — Reservation после глобальной карты

## Что исследовано
Разделение townid/фон/overlay; renderer9de154; оригинальные8589c4/8596e0.

## Что доказано
По сообщению пользователя глобальнаякартазагрузилась. Live диагностический
8596e0 приводит к render-loop9de154,загрузкеpda/loc_reserve.jpg и loaded1/id3.
Mode до вызова уже1; проблема не доказана как простое отсутствиефлага.

## Новые packet mappings
F0 command98 вынесенвпроверяемыйcodec. Новыхответов50пока нет.

## Новые структуры
system_message.py: ограниченныйcodec currenttown,не весь SystemMessage.

## Изменённые файлы
Codec/tests,loopback,capture townview/texturehooks,RESERVATION.md,NEXT_TASK,
CITY_ENTRY,evidence. --town-view-probe валидирует зависимостьenter-town-probe.

## Добавленные тесты
64 unit PASS. Live toggleprobe,explicit-town-view и textureloadprobe.
Повторный ранний запуск корректно отказался из-за ещёработавшего ownedprobe
и существующегоitems.xml; дождались завершения и повторили без удаленияданных.

## Что остаётся неизвестным
Обычный вход без диагностическогоcallback; ответ50; визуальная сцена.

## Риски / альтернативные интерпретации
Nativecallback в probe не заменяет сервернуюреализацию. 8589c4 toggles mode0
при mode1;8596e0 открывает/обновляетгород. Не объявлятьцельзавершённой.

## Следующий самый полезный шаг
Штатный переход с карты в Reservation безnativeprobe,затем визуальнаяпроверка.

---
# Рабочий цикл — команда текущего города и диагностика UI

## Что исследовано
Startup окна/основной поток; writes current_town; F0 decoder и command switch.

## Что доказано
F0 command98(type1 town3) принят оригинальным клиентом: current_town3,
автоматический запрос5003. Повторный held probe подтвердил current_town.

## Новые packet mappings
F0 command98 с однимu32аргументом; C2S50+u8town. Ответ покаUNKNOWN.

## Новые структуры
Исследован envelope F0: command/count/type/value. В production codec ещё
не вынесен; ограничен opt-in диагностическим probe.

## Изменённые файлы
capture_loaded_orange.py: tracewindows/checkpoints/commandhook;
loopback_exchange.py: commandtrial и исправленный observationloop;
probe_windowed.py: обратимая смена режима; CITY_ENTRY,NEXT_TASK,evidence.

## Добавленные тесты
63 прежнихunit PASS; livecommand98 и повторный heldprobe;
оконный/fullscreenstartup и стеки потоков. Новыхunit нет.

## Что остаётся неизвестным
Ответ50,полная городская сцена,почемуskyнеобнаруживает игровуюформу.

## Риски / альтернативные интерпретации
current_town3 не доказывает видимыйвход. ShowWindow вызывается;
ShowMainForm1 и живой idle исключают прежнее предположение о непоказевсехокон.
Rawflag76dab4 семантическиUNKNOWN,не считать его loading по именипервогоhook.

## Следующий самый полезный шаг
Ответ5003 и дальнейший городскойbootstrap с доказательством сцены.

---
# Рабочий цикл — сетевой TownInfo C8/2D

## Что исследовано
Serializer64a650,decoder64a3fc,wrapper7d089c,consumer7cec78.

## Что доказано
Два live запуска приняли C8/2D; второй подтвердил изменение записи города3.
Оригинальный декодер потребил37bytes без optional payload.

## Новые packet mappings
CONFIRMED C8/2D TownInfo. Предыдущий вывод о wire3C отозван:
60 в диагностическом wrapper не определяет сетевой префикс.

## Новые структуры
TownInfoBase: сохранение неизвестных полей и raw float bits; optional branches
явно отклоняются, пока не реализованы.

## Изменённые файлы
town_info.py, test_town_info.py, verify_town_native.py, loopback и capture tools;
CITY_ENTRY, NEXT_TASK, packet/status docs, evidence. Явный SW_SHOWNORMAL для probe.

## Добавленные тесты
63 unit PASS; native decoder PASS; два live loopback probes с возвратом обработчика.
Во втором запись id3 получила bytes[1,3,0,0] и float bits0x3f800000.

## Что остаётся неизвестным
Семантика неизвестных полей, optional blocks, реальный переход и видимое окно.

## Риски / альтернативные интерпретации
Обновление данных города не доказывает вход в город. Значения диагностические.
После изменения show flags визуальная проверка ещё не выполнена.

## Следующий самый полезный шаг
Условия перехода7cec78/775be4 и startup GUI; затем реальный вход с визуальным доказательством.

---
# Рабочий цикл — выбор и bootstrap к городу

## Что исследовано
Selection callback8a3108,builder17,18/1A,XMLzones,структурированныйTownInfo.

## Что доказано
Live17→18→19→1A,parser returns. B9zones загрузил3города вместоNULLtable.

## Новые packet mappings
17 optionalCString;18 conditional2u32;19 request;1A full fields;TownInfo: прежний вывод о wire3C отозван в новом цикле выше.

## Новые структуры
SelectResult,MyCharInfo codecs;source-backed diagnosticzones XML.

## Изменённые файлы
world_bootstrap.py,test_world_bootstrap.py,probe/loopbackselection/mychar,
visiblelaunch option,zonesfixture,evidence,CITY_ENTRY.md.

## Добавленные тесты
61 unit PASS;live selection,mychar,zones delivery и window discovery.

## Что остаётся неизвестным
TownInfo schema,actual city transition,visible UI startup.

## Риски / альтернативные интерпретации
Город не открыт;skyнеобнаружилокно.1Au16 остаётсяUNKNOWN.
AZTreferenceTownInfo несовместим;не использован.

## Следующий самый полезный шаг
СтруктурированныйTownInfo3C и видимый UI;цель входа в город остаётсяactive.

---
# Рабочий цикл — диагностическое создание с сохранением

## Что исследовано
Обработка нового10 после11,flagac4c58/aliasac5940,setter9dc760 и parser12.

## Что доказано
List-only trial оставляет gate1.1200→10 принимает сохранённую запись и сбрасывает
флаг в0. Совместимость подтверждена live, официальный success code не установлен.

## Новые packet mappings
Новых opcode нет; подтверждена диагностическая последовательность11→1200→10.

## Новые структуры
CharacterStore SQLite: account,slot,name,name_key,original requestBLOB.

## Изменённые файлы
characters.py,test_character_store.py,loopback/probe positive mode,документы/evidence.

## Добавленные тесты
59 unit PASS, persistence/reopen,isolation,rejections.3 live trials,финальныйPASS.

## Что остаётся неизвестным
Полные options/profile,official success semantics,UI submit,reconnect,выбор/18.

## Риски / альтернативные интерпретации
Это ограниченный diagnostic profile и политика1char/account;0 всё ещё unknown
branch клиента. Первый storage test обнаружил незакрытые connections,исправлено.

## Следующий самый полезный шаг
Выбрать сохранённого персонажа через original callback и восстановить18.

---
# Рабочий цикл — запрос создания персонажа

## Что исследовано
Builder889cdc, UI caller8a3062, u16 writer6e1d94, result88a79c,локализации.

## Что доказано
C2S11 layout;S2C12 statuses1–4 errors. Live11→1204 прошёл оригинальным клиентом.

## Новые packet mappings
11 CharacterCreate;12 CharacterCreateResult. Default0 не доказан как success.

## Новые структуры
CharacterCreateRequest(name_bytes,unknown_u16,options4), result u8 codec.

## Изменённые файлы
character_create.py,test_character_create.py,verify_character_create_native.py,
probe/create loopback hooks, CHARACTER_CREATION.md и evidence.

## Добавленные тесты
57 unit PASS;6 native result branches PASS;live request+invalid-name result PASS.

## Что остаётся неизвестным
Success sequence, option meanings, persistence и UI callback prerequisites.

## Риски / альтернативные интерпретации
Первый live probe failed из-за lifetime буфера trampoline, повтор после fix PASS.
Вызван builder, не UI callback;нет успешного создания/сохранения персонажа.

## Следующий самый полезный шаг
Доказать positive creation flow и только затем добавить persistence/обновление10.

---
# Рабочий цикл 2026-09-12 — штатная загрузка каталога и непустой10

## Что исследовано
XML attribute/property helpers TI, оригинальный items.cfg, loadera7005c,
сетевой shared-config bootstrap и повторный CharSelectInfo.

## Что доказано
CONFIRMED B9 доставляет zlib XML, клиент распаковывает его побайтно точно,
выделяет каталог и полностью обрабатывает Probe. Возврат889eac подтверждён.

## Новые packet mappings
Новых opcode нет. Подтверждён live порядок B9/01,02,03,04 перед10.

## Новые структуры
Диагностический XML с id/name attributes и child key/val properties;
две записи0,300 из TI items.cfg с provenance и списком пропущенных полей.

## Изменённые файлы
build_item_fixture.py,probe_item_fixture.py,capture_loaded_orange.py,
loopback_exchange.py,test_shared_config_delivery.py, XML/provenance/evidence,
SHARED_CONFIG.md и документы статуса.

## Добавленные тесты
54 unit tests PASS. Два новых socketpair cases: encryption/order/compression
и отказ при неверном ответе. Три live запуска: loader, loader+10, networkB9+10.

## Что остаётся неизвестным
Выбор персонажа, ответ18, world entry,полный каталог/schema/checksum algorithm.

## Риски / альтернативные интерпретации
Две частичные диагностические записи достаточны только для наблюдённого10.
UI внешний вид не проверен, login/selection hooks остаются частью probe.
Success parser не означает пригодность всей игровой модели или экономики.

## Следующий самый полезный шаг
Восстановить штатный callback выбора персонажа, C2S builder и ответ18.

---
# Рабочий цикл — восстановлен B9/03

## Что исследовано
9d0484,copy605f4c,file writer a89740,decompressor6878ec и TZDecompressionStream.

## Что доказано
Имя + два u32 размера + сжатые байты. Целый файл сохраняется, распаковывается,
перезаписывается и передаётся reload. Runtime root снят у оригинального клиента.

## Новые packet mappings
Уточнён S2C B9/03; новых opcode не добавлено.

## Новые структуры
SharedConfigData(name_bytes,decompressed_size,compressed_bytes), strict codec.

## Изменённые файлы
shared_config.py,test_shared_config.py,verify_shared_config_data_native.py,
capture_loaded_orange.py (read-only root snapshot), документы и evidence.

## Добавленные тесты
52 unit PASS;3 original-x86 data read/copy cases PASS, включая50000 bytes.

## Что остаётся неизвестным
TI XML schema/content,comparison algorithm,live decompression/loading.

## Риски / альтернативные интерпретации
Native probe останавливается до filesystem; это не успех загрузки ресурсов.
WindowBits15 подтверждён, zlib payload ещё не проверен оригинальной распаковкой.
Предельный copy размер соблюдает encoder, сам client helper его не проверяет.

## Следующий самый полезный шаг
Восстановить schema TI items.xml, проверить обоснованный fixture штатным loader.

---
# Рабочий цикл — найдена shared-config зависимость

## Что исследовано
Owner/allocator таблицы ac637c, boundac4e70, XML loader и сетевые callers.

## Что доказано
Таблица выделяется a7005c при чтении shared config\items.xml. Её reload связан
с B9 shared-config protocol. Live повтор подтвердил NULL и отсутствие reload.

## Новые packet mappings
B9/01 SharedConfigSet; B9/03 SharedConfig; C2S B9/02 запрос имени, B9/04 builder.
Полностью восстановлен только wire layout B9/01.

## Новые структуры
SharedConfigEntry(name_bytes,comparison_value); u8 count, CString+u32LE.

## Изменённые файлы
shared_config.py, test_shared_config.py, verify_shared_config_native.py;
startup catalog hooks в capture_loaded_orange.py; SHARED_CONFIG.md и evidence.

## Добавленные тесты
3 unit tests (всего50 PASS),2 original-x86 manifest cases PASS.

## Что остаётся неизвестным
Полный B9/03, comparison algorithm, источник и schema items.xml, runtime root.

## Риски / альтернативные интерпретации
Live nonempty10 FAILED, ресурсы ещё не восстановлены. Native loader stubbed.
Отсутствие файла проверено в установленном TIOnline, не во всех каталогах ПК.

## Следующий самый полезный шаг
Восстановить B9/03 и обеспечить штатное заполнение таблицы, затем повторить10.

---
# Рабочий цикл 2026-09-12 — непустая запись персонажа

## Что исследовано
Полный RECV_CharSelectInfo889eac, nested6d01f8, numeric readers, resource setter,
обновление моделиa855ac и faulting lookup a78afc.

## Что доказано
CONFIRMED полный wire layout, conditional6 bytes,19 words, final fields.
Native parser проверен. Live чтения завершились, но сам parser не вернулся:
при обновлении модели NULL resource table вызвала fault a78b1c/address116.

## Новые packet mappings
Уточнён S2C10: полная запись54+name_length bytes, +6 при optional flag.
Новых игровых opcode не выдумано.

## Новые структуры
CharacterRecord и strict encode/decode_character_list; неизвестные поля сохранены
без игровых названий. Empty codec сохранён.

## Изменённые файлы
character_select.py, tests/test_character_record.py, native record verifier;
probe получил single-record mode и checkpoints. Cleanup завершает только свой
процесс до detach. CHARACTER_RECORD.md, реестр, FSM, README, RE_FINDINGS,
NEXT_TASK обновлены; raw traces, ASM и resource reference сохранены.

## Добавленные тесты
4 новых unit tests, всего47 прошли.3 original-x86 cases прошли: полный parser
с/без optional block и воспроизведение NULL catalog fault. UI/lifecycle/strings
в parser harness stubbed; original primitive/nested readers выполняются.

## Что остаётся неизвестным
Owner/init таблицы [[ac637c]], смысл многих полей10, prerequisites before10,
выбор персонажа/18 и world entry.

## Риски / альтернативные интерпретации
Live nonempty10 FAILED после чтения записи. Корректный layout не доказывает
пригодность synthetic значений и готовность runtime ресурсов. Mobs id1 существует,
но этого недостаточно для загрузки модели. Native stubs исключают зависимость,
которая и проявилась в живом клиенте. Ресурсные pointers не патчились.

## Следующий самый полезный шаг
Восстановить штатную инициализацию resource table, затем повторить ту же запись10.
Переход к выбору персонажа пока преждевременен.

---
## История предыдущих циклов

# Рабочий цикл 2026-09-12 — начало выбора персонажа

## Что исследовано
Основной gate export9f5548, character dispatcher88b33c,
RECV_CharSelectInfo889eac, empty branch иначало nonempty reader.

## Что доказано
CONFIRMED:10 сcount0 после0D проходит gate, вызывает обновлениевыбора8a2868,
ставит[ac5814]=1 ивозвращается. Обработан настоящийклиентскийparser.
ПоказUI визуально инепустойсписок ещёнепроверены; world entry недостигнут.

## Новые packet mappings
S2C10 → CharSelectInfo: u16 count. Точнаяempty форма100000.
Найдены mappings12/14/18/1A/1C; порядокихиспользования неутверждается.

## Новые структуры
Exact empty character-list encoder/decoder. Полнаязапись не реализована,
поскольку включает вложенныйreader6d01f8 идополнительныеполя.

## Изменённые файлы
`tio/protocol/character_select.py`, тесты, native character/gate verifier;
loopback/capture расширены на10 иhooks. Guard loader допускаетужеuser32slot
безpatch; неизвестныйslot не меняет. CHARACTER_SELECTION.md, реестр, FSM,
README, RE_FINDINGS, NEXT_TASK обновлены; ASM иtrace сохранены.

## Добавленные тесты
2 новыхunit tests, всего43 прошли.6 original-x86 tests:2 emptyparser UI paths,
4 сочетанияgate/override. UI/lifecycle/прочиеdispatchers явноstubbed.
Дваlive runs приняли10; повторныйrun безошибокinstrumentation.

## Что остаётся неизвестным
Полнаязапись10, семантикаgate flag, выборперсонажа/18, MyCharInfo/world,
порядокbootstrap packets, поздниеtransport modifications.

## Риски / альтернативные интерпретации
Первыйrun имелошибкуhook из-заотсутствующегоapphelp, ноуспешнообработал10.
Повтор подтвердил ужеcorrect user32slot безpatch иуспешный10. Native harness
проверяетусловия/consumption/flag stores, неUI; live hooks неравнывизуальнойпроверке.
Локальныйпорядок0D→10 принят, нооригинальнаясервернаяпоследовательность неизвестна.

## Следующий самый полезный шаг
Восстановить одну полнуюзаписьCharSelectInfo10 ивложенныйreader6d01f8,
затемпроверитьнепустойсписок иперейти квыборуперсонажа.

---
## История предыдущих циклов

# Рабочий цикл 2026-09-12 — AuthReply2

## Что исследовано
SILVER AuthReply2 по87d8a4, success/error branches, logger6061b0,
источники двух CString запроса0C и начало основной цепочки dispatchers.

## Что доказано
CONFIRMED:0D00 принят, клиент записал сообщение об успешной game auth,
обработчик вернулся. Success-ветка только логирует, нового builder нет.
Новых C2S bytes за2s наблюдения не было. World entry не подтверждён.

## Новые packet mappings
C2S0C: opcode/две CString. S2C0D: opcode/status.
Вторая строка0C повторяет trailing06; смысл первой UNKNOWN.

## Новые структуры
Auth2Request с raw byte strings; strict request/result codecs.
S2C0D использует продолжение game cipher после0B.

## Изменённые файлы
`tio/protocol/auth2.py`, `tests/test_auth2.py`, `tools/verify_auth2_native.py`;
loopback/capture расширены на0D и AuthReply2 logger/return hooks. AUTH2.md,
registry/FSM/README/RE_FINDINGS/NEXT_TASK обновлены; ASM/live/native evidence сохранены.

## Добавленные тесты
4 новых unit tests, всего41 прошли: golden0C, CString boundaries/truncation,
все256 статусов, encrypted0D continuity.3 original-x86 cases0/1/255 прошли:
consumption1, success log address и error UI path. Живой0D успешен.

## Что остаётся неизвестным
Первое серверное сообщение инициализации игрового состояния, семантика строк0C,
порядок world packets, object+1ab и поздние transport modifications.

## Риски / альтернативные интерпретации
Сообщение game auth success не означает готовность мира или настоящую проверку
аккаунтов. У native harness logging/UI/string helpers stubbed; live hooks проверяют
фактический logger. Отсутствие C2S за2s не исключает поздние события. Порядок
handlers в export не является порядком сообщений. Данные/выбор в probe синтетические.

## Следующий самый полезный шаг
Восстановить gate основной dispatch chain и минимальную серверную инициализацию
персонажа/локации. Следующего автоматического C2S после0D ожидать оснований нет.

---
## История предыдущих циклов

# Рабочий цикл2026-09-12 — mode1 handshake

## Что исследовано
ORANGE mode1 initialization1a90, dispatcher09/0B, key derivation, reply0A,
SILVER AuthReply1 иследующийapplication0C.

## Что доказано
CONFIRMED: state2/cipher0 → clear09 → derived key/cipher1 → encrypted0A →
encrypted0B00 → state3/queued0B → AuthReply1 → realapplication0C.

## Новые packet mappings
09 = opcode/raw8;0A = opcode/previous transformed u32/completion u32;
0B = opcode/status. Application0C captured какopcode+двеCString.

## Новые структуры
Mode1Reply иstrict09/0B codecs, clearfirst-frame encoder; InitialCipher принимает
проверенный8-byte initialkey, defaultlogin key сохранён.

## Изменённые файлы
`tio/protocol/mode1.py`, transport.py, tests/test_mode1.py,
verify_mode1_native.py; loopback/capture расширены на09/0A/0B/0C.
MODE1_HANDSHAKE.md, registry/FSM/README/RE_FINDINGS/TRANSPORT/NEXT_TASK обновлены,
live/native logs иASM сохранены.

## Добавленные тесты
4 новыхunit tests;37 прошли.15 original-x86 cases прошли:09 seeds/short packets,
cipher2680 сderived key,0B statuses иwrongstate.8 прежнихnative cipher cases
тоже прошли послеизмененияconstructor. Liveполныйпереход до0C успешен.

## Что остаётся неизвестным
Семантикастрок0C, ответ0D, object+1ab/поздниеwire modifications, world protocol.

## Риски / альтернативные интерпретации
Первый09-run показалошибкуexpectation:0A firstu32 берётсяизвтороговычисленного01,
неизтретьегополя. ASM/trace подтвердилиисправление, failedrun сохранён.
Mode — byte; hook исправлендляигнорированиястаршихбитов. Originalgame handshake
проверен послеlogin, coldmode1 непроверен. Native send/queue stubbed; liveвыход
подтверждаетихреальноеисполнение. World readiness непроверена.

## Следующий самый полезный шаг
Восстановить application0C/0D (AuthReply2 по87d8a4), затем проверить
следующийoriginal callback/packet безсмешиванияlogin/game cipher states.

---
## История предыдущих циклов

# Рабочий цикл2026-09-12 — выбор сервера07/08

## Что исследовано
Caller71e998→builder87c7b4, raw8 writer7f9dc0, parser08 по87d400,
connect wrapper606080; новыйsocket после реального08.

## Что доказано
CONFIRMED: выборactual record создаёт07;0800 вызывает connect к егоhost/port
вmode1. ВторойTCP accept успешен. Record+4/+8 теперь доказаны какaddress/port.

## Новые packet mappings
C2S07 = opcode/server_id/raw8; S2C08 = opcode/status. Status0 открывает новое
соединение; значения ненулевых ошибок остаются UNKNOWN.

## Новые структуры
ServerLoginRequest(server_id,unknown_bytes_01[8]), checked08 status codecs.
Адрес/порт сохраняются локально; не включены в07.

## Изменённые файлы
`tio/protocol/server_login.py`, `tests/test_server_login.py`, native08 verifier;
loopback/capture расширены наoriginal selection иsecond accept; SERVER_LOGIN.md,
registry/FSM/README/RE_FINDINGS/NEXT_TASK обновлены, ASM/live/native evidence сохранены.

## Добавленные тесты
2 новых unit tests, всего33 прошли:07 layout/live fixture/границы/truncation,
08 все256 statuses иinvalid wire.3 original-x8608 cases прошли:0/1/255,
consumption иexact connect args. Live original07/0800/второйsocket успешны.

## Что остаётся неизвестным
Смыслraw8, optional connect string, mode1 handshake/cipher, object+1ab,
поздние wire modifications иworld protocol.

## Риски / альтернативные интерпретации
Original selection вызван изhook, не UI click; синтетически выбранindex0.
Nested builder hook не доставленFrida, но actual07 принят сервером и0800
вызвал original connect. На новомsocket2s не былоbytes — не доказательство формата.
Native08 tests stubs UI/strings/connect; live проверка дополнительно подтверждает
реальныйsocket. Client selection может сохранять обычные preferences.

## Следующий самый полезный шаг
Восстановить начальныйmode1 handshake итолько затем отправлять первыйgame frame.
Initial codec не считать универсальным для второго соединения.

---
## История предыдущих циклов

# Рабочий цикл 2026-09-12 — список серверов06

## Что исследовано
SILVER parser87d1cc, builder05 по87c76c, primitive readers, CString, record stores,
функция обновления71e594; два живых обмена с исходным клиентом.

## Что доказано
CONFIRMED:06 поддерживает пустой список и записи12 bytes, завершается CString.
Исходный клиент принял пустой иsingle-entry06, создал запись и вызвал refresh.
Серверный список пройден на уровне parser/callback; UI выбор ещё не проверен.

## Новые packet mappings
C2S05 = opcode/u8/u32LE/CString. S2C06 = opcode/count/u8/records12/CString.
Семантика большинства полей UNKNOWN; подробная таблица — SERVER_LIST.md.

## Новые структуры
ServerEntry, ServerList, ServerListRequest. Числа и строки без выдуманных названий.
Codec строго проверяет12 bytes на запись иNUL; native guard требует только10.

## Изменённые файлы
`tio/protocol/server_list.py`, `tests/test_server_list.py`,
`tools/verify_server_list_native.py`; расширены loopback/capture probe, добавлена
проверка SHA silver.dll до запуска. SERVER_LIST.md, реестр, FSM, RE_FINDINGS,
README и NEXT_TASK обновлены; ASM, live/native evidence сохранены.

## Добавленные тесты
5 новых unit tests (всего31 прошли): golden empty/entry/request05, count255,
CString255, malformed/truncation/trailing.7 original-x86 cases прошли. Native
harness явно stubs UI/allocator/string management/numeric conversion; исходные
parser и byte/word readers работают. Два live runs: пустой иодна запись успешны.

## Что остаётся неизвестным
Значение header/trailing fields, точная семантика record fields, выбор сервера,
07/08 layouts, поздние transport counters и игровой протокол.

## Риски / альтернативные интерпретации
IPv4 STRONG по decimal-dot construction, port LIKELY; codec сохраняет raw fields.
Synthetic values не означают доказанную игровую конфигурацию. Live refresh hook
не подтверждает визуальный UI. Отсутствие C2S за2s не означает, что07 не нужен.
Клиентские binaries/config не патчатся; compatibility fix только вowned process.

## Следующий самый полезный шаг
Восстановить выбор сервера, builder07 по87c7b4 и response08 по87d400, затем проверить
реальный07. Перед длинной сессией восстановить counter-dependent transport.

---
## История предыдущих циклов

# Рабочий цикл 2026-09-12 — completion и basic login

## Что исследовано
ORANGE completion02/queue; SILVER03 builder, CString helpers, success04.

## Что доказано
## Актуальный результат 2026-09-12

CONFIRMED: оригинальный TI по TCP loopback прошёл `S2C transport00 → C2S01 →
S2C transport02 → C2S application03 → S2C application0400 → C2S application05`.
Completion `02000044332211` создаёт очередь `020044332211` и native state0→1.
Transport02 сам доставляет LSAuthResult; отдельный application02 не нужен.

Connect вызван через оригинальный экспорт. В оригинальный builder поданы
синтетические ASCII credentials `probe_user / probe_password` в памяти процесса.
Socket, cipher, parser и builder выполняются оригинальным клиентом; полный UI login
и реальная серверная аутентификация не проверены. Следующий blocker — ответ06.
26 unit tests и 9 original-x86 completion cases прошли. Evidence:
`evidence/login_success_run.log`, `evidence/native_completion_probe.json`.
Counter-dependent изменения транспорта после >5/>6 остаются UNKNOWN.

## Новые packet mappings
Transport02 → local application02; basic C2S03; S2C0400 → C2S05.

## Новые структуры
InitialCompletion, BasicLoginRequest с raw-byte CString, strict success04 codec.

## Изменённые файлы
`tio/protocol/transport.py`, `tio/protocol/login.py`, `tests/test_completion.py`,
`tools/verify_completion_native.py`, `tools/loopback_exchange.py`, guarded capture
probe; документы и evidence. Probe собирает TCP fragments с общим deadline5s.

## Добавленные тесты
5 новых unit tests: golden wire/key continuity, границы, truncation, basic03,
strict0400. Всего26 прошли. 9 original-x86 completion cases: 6 success,2 failure,
1 wrong state. Queue call stubbed, исходные parser/readers/writers выполняются.

## Что остаётся неизвестным
Layout06, семантика полей05, non-ASCII encoding, optional03/0A,
поздние counter-dependent изменения транспорта, игровой вход/world.

## Риски / альтернативные интерпретации
Probe вызывает connect export, credentials подаёт в регистры builder; UI ввод
не проверен. Синтетическая проверка не является реализацией account database.
Failure completion проверен на x86, не live UI. Initial codec ограничен началом.

## Следующий самый полезный шаг
Восстановить RECV_LSServerList0x87d1cc и реализовать минимальный доказанный06.
Подробный порядок и команда воспроизведения — NEXT_TASK.md.

---
Повторный live запуск после исправления TCP чтения также достиг05; лог —
`evidence/login_success_repeat.log`.

## История предыдущих циклов

# Рабочий цикл 2026-09-11

## Последний завершённый этап — initial transport, 2026-09-12

### Что исследовано

Оригинальные unpacked socket wrapper, frame writer/reader, XOR, dispatcher и
challenge/reply; настоящий TCP loopback с процессом ti.exe.

### Что доказано

CONFIRMED: начальный кадр u16_le total length; XOR действует уже при начальном
mode0 соединении; шифрование/расшифрование имеют разные обходы ключа и обновления.
Оригинальный transport принял S2C00 и вернул C2S01 с правильными вычисленными полями.

### Новые packet mappings

ORANGE transport 00 challenge →01 reply. Они отличаются от application opcodes.
Transport02 completion пока только найден в коде, live transition UNKNOWN.

### Новые структуры

InitialChallenge, InitialReply (с opaque unknown_bytes[3]), InitialCipher,
InitialFrameReader с TCP fragmentation/coalescing. Неподтверждённые поля не названы
account/session token без доказательств.

### Изменённые файлы

tio/protocol/transport.py, tests/test_transport.py, tools/verify_transport_native.py,
tools/loopback_exchange.py; расширен guarded capture probe на один loopback endpoint.
TRANSPORT.md, PACKET_REGISTRY, FSM, RE_FINDINGS, README, NEXT_TASK обновлены.
В evidence сохранены реальные wire bytes, failed controls и оригинальные ASM.

### Добавленные тесты

6 новых unit-тестов, всего **21 прошёл**: live golden bytes, roundtrip,
все TCP split positions, coalescing, границы, неверные поля/длины/truncation.
**8 original-x86 cipher/state cases прошли**, четыре последовательных вызова
на направление. Новый codec повторно проверен настоящим ответом оригинального
TI-транспорта, оба transformed u32 совпали.

### Что остаётся неизвестным

Семантика flags/третьего u32/трёх tail bytes, completion02 callback,
последующая auth-последовательность, game mode, counter-dependent wire modifications.

### Риски / альтернативные интерпретации

Probe вызывает оригинальный connect export, но не кнопку UI: wire path настоящий,
полный UI login не проверен. Initial codec не предназначен для неограниченного
трафика: после счётчика +0x1ab >5/>6 исходный код изменяет длину/байты.
Tail различается между запусками; его смысл UNKNOWN. Empty frame rejection —
явная политика сервера, а не копия небезопасных клиентских length checks.

### Следующий самый полезный шаг

Восстановить и проверить транспортный S2C02 completion после C2S01 в том же
соединении с сохранённым ключом; проследить queued callback и следующий
application producer. Полный вход ещё не объявляется завершённым.

---

## Обновление рабочего цикла 2026-09-12

### Что исследовано

Protected ORANGE initializer, resolver RVA 0xbc80, CRC32 helper 0x6b5c,
runtime module table и реальные export destinations.

### Что доказано

CONFIRMED: GetCursorPos искался в apphelp.dll вместо user32.dll. Исправление
одного указателя в памяти устраняет loader failure; три запуска успешны.
Сохранён оригинальный код транспорта в отдельной области 28672 байта.

### Новые packet mappings

Нет: работа касается загрузчика. 11 экспортов сопоставлены с адресами
распакованных функций в ORANGE_LOADER.md.

### Новые структуры

Подтверждён module-table slot RVA 0x4a13. Игровые структуры не добавлены.

### Изменённые файлы

tools/capture_loaded_orange.py: guarded process-only fix и отдельный dump
unpacked allocation; tools/inspect_cfg.py: обход прямых переходов через junk;
tools/seal_evidence.py: recursive manifest. Обновлены README, NEXT_TASK,
SESSION_STATE_MACHINE, RE_FINDINGS, .gitignore. Добавлены ORANGE_LOADER.md,
tests/test_loader_evidence.py, logs и snapshots.

### Добавленные тесты

4 новых теста; 15 всего прошли. Guarded live probe отдельно подтвердил
успешную загрузку и получение snapshots. Бинарники проверяются по SHA до запуска.

### Что остаётся неизвестным

Причина выбора неправильного модуля, framing, cipher, handshake. Сетевой вход
не выполнен; постоянный patch клиента не установлен.

### Риски / альтернативные интерпретации

LIKELY: зависимость от порядка модулей; UNKNOWN точный алгоритм неправильного
выбора. Снимки памяти не являются rebuilt PE. Часть SEH faults намеренная.
Исправление проверено в текущем build/окружении, не объявляется универсальным.

### Следующий самый полезный шаг

Восстановить framing и handshake из сохранённого TI transport; затем первый
loopback exchange оригинального клиента. Подробности в NEXT_TASK.md.

---
История первого цикла:

## Что исследовано

Пустой рабочий каталог, полный TI client tree (4556 файлов), reference AZT tree
(9463 файлов), PE metadata/strings, TI login dispatcher, auth consumer, loader
orange.dll, общий file/string/XML/function subset TI↔AZT.

## Что доказано

**CONFIRMED:** application 02 → RECV_LSAuthResult; status u8; при 0 — u32_le,
store и вызов login-builder. Формула обработки u32 восстановлена по x86.
LoadLibraryW("orange.dll") в instrumented launch возвращает 1114; контроль
с поздним attach тоже не имеет transport module/function pointer.

**LIKELY:** сохранённый u32 имеет смысл challenge/token; loader fault связан
с совместимостью protected initializer с текущей средой.

**UNKNOWN:** framing, первый TCP packet, точная причина сбоя packed initializer,
полный login request, server-list records и переход в world.

## Новые packet mappings

02 LSAuthResult; 04 LSLoginResult; 06 LSServerList; 08 LSServerLoginResult;
0B AuthReply1; 0D AuthReply2 — подтверждены в TI application dispatcher.
00/01 — локальные connection/disconnection callbacks, не wire mappings.

## Новые структуры

`LSAuthResult(status, unknown_u32_01?)`, проверяемые binary primitives и
JSONL trace records с контекстом/связями соседних пакетов. Модели персонажа,
предметов и боя не выдумывались.

## Изменённые файлы

Созданы `tio/protocol/{binary,login,trace}.py`, offline CLI, tests и research
tools; FILE_INVENTORY, PACKET_REGISTRY, SESSION_STATE_MACHINE, RE_FINDINGS,
GAMEPLAY_VERSION, ITEM_SYSTEM, обе TI_AZT карты, README и NEXT_TASK.
Raw evidence, исходные bytes+адреса, XML/config diffs и результаты native probe
сохранены в `evidence/`. Существующего кода для переписывания не было.

## Добавленные тесты

**11 unit-тестов прошли**, включая golden bytes, все ненулевые status,
границы u32, неверные длины/opcode/поля, endian и unknown trace logging.
**9 original-x86 dispatcher/parser cases + 5 original-x86 arithmetic cases
прошли** в Unicorn с явно перечисленными UI/builder заглушками.

## Что остаётся неизвестным

Реальный wire exchange отсутствует: оригинальный transport не загрузился.
Работающий login-server milestone **не завершён**. Есть подтверждённая
реализация одного application response, но ещё нет socket server.

## Риски / альтернативные интерпретации

Нельзя принять synthetic golden за захваченный пакет, native probe — за
успешный вход, callback opcode — за wire event, identical assets — за одинаковый
протокол. Причина 1114 не установлена; часть исключений unpacker намеренная.
Полный buffer length может допускать расширения: strict suffix rejection —
политика текущего codec, а не подтверждённое ограничение оригинального parser.

## Следующий самый полезный шаг

Восстановить успешную инициализацию **TI orange.dll** и получить её рабочий
распакованный образ; затем доказать framing и снять первый loopback exchange.
После этого подключить готовый 02 codec и проверить исходящий 03 запрос
оригинального клиента. Конкретные точки и команды — в NEXT_TASK.md.

## 2026-09-12 — Wear button request binding

1. Что исследовано: m492 button binding, closure interface and item action writer.
2. Что доказано: original8d4ab8 passes pet17/item1001/null target; missing selection/owner returns without action. Original9903a4 emits33 in three marker cases.
3. Новые packet mappings: shared C2S33 pet:u32/item:u32/option:u8.
4. Новые структуры: ItemAction; option remains raw.
5. Изменённые файлы: native verifier, protocol/item_action.py, tests/test_item_action.py, INVENTORY.md, NEXT_TASK.md, evidence.
6. Добавленные тесты: native callback3/writer3; codec native fixtures and malformed packets.141 unittest PASS.
7. Что остаётся неизвестным: intermediate policy runtime, slot mapping, authoritative response and persistence.
8. Риски и альтернативы:33 also serves consumables; treating all requests as equip would be incorrect. Managed/UI/metadata boundaries isolated in native verifier.
9. Следующий самый полезный шаг: run a6516c with real equipment metadata, then implement scoped equipment mutation and client update.

## 2026-09-12 — Explicit item target mapping

1. Что исследовано: original a7a050 called by a6516c for explicit target.
2. Что доказано:25 original executions establish19 target indices and FF fallback.
3. Новые packet mappings:33 final byte is target index for this path, not raw mask.
4. Новые структуры: TARGET_MASKS and ItemAction.target_mask.
5. Изменённые файлы: item_action.py, test_item_action.py, verify_item_target_native.py, evidence and inventory notes.
6. Добавленные тесты: original25 input cases and codec target interpretation;142 tests PASS.
7. Что остаётся неизвестным: automatic equipment selection, full policy with real metadata, server response.
8. Риски и альтернативы: incoming inventory normalization and outgoing target conversion are different; unsupported masks must not be silently treated as4.
9. Следующий самый полезный шаг: recover actual item metadata for full policy and implement scoped persistent equipment action.

## 2026-09-12 — Complete policy execution

1. Что исследовано: a6516c and local items.cfg301/326.
2. Что доказано: complete original policy returns with target optionsFF/0/4/7; ordinary target40000 is blocked.
3. Новые packet mappings: none;33 target propagation confirmed across policy.
4. Новые структуры: none.
5. Изменённые файлы: verify_item_policy_native.py, evidence/item_policy_native.json, inventory/next-task notes.
6. Добавленные тесты:5 native policy cases PASS; production code unchanged.
7. Что остаётся неизвестным: real item compatibility metadata loading and server equipment update.
8. Риски и альтернативы: synthetic metadata and predicate stubs do not establish real catalog acceptance. Flag+68d gate requires investigation.
9. Следующий самый полезный шаг: shared-config item metadata defaults/loading, then real equipment path.

## 2026-09-12 — Equipable default correction

1. Что исследовано: XML loader a7341f and boolean helper680860.
2. Что доказано: missing equipable key writes metadata+68d=1 by original instructions.
3. Новые packet mappings: none.
4. Новые структуры: XML equipable boolean, default true.
5. Изменённые файлы: verify_equipable_default_native.py, evidence and inventory notes.
6. Добавленные тесты: original loader/default/helper/write native PASS; no production changes.
7. Что остаётся неизвестным: type/slot compatibility and persistent equip update.
8. Риски и альтернативы: previous presumed missing-flag prerequisite disproved; no invented fixture fields needed. Dictionary absence is isolated, not a full XML parser test.
9. Следующий самый полезный шаг: item type defaults and real target compatibility, then server action.

## 2026-09-12 — Item type default

1. Что исследовано: loader type/itype block a713cf..a719a8.
2. Что доказано: original initialization writes metadata+118=1; isolated empty-key path retains1.
3. Новые packet mappings: none.
4. Новые структуры: default metadata type1; semantic label not asserted.
5. Изменённые файлы: verify_item_type_native.py, item_type_native.json, NEXT_TASK.md.
6. Добавленные тесты: empty-key native path PASS.
7. Что остаётся неизвестным: nonempty variant comparison behavior; equipment compatibility.
8. Риски и альтернативы: attempted managed comparison stubs did not establish nonempty mappings; no such mapping accepted. Prefer actual runtime/live metadata.
9. Следующий самый полезный шаг: original variant comparisons or live metadata snapshot instead of further assumed string predicates.

## 2026-09-12 — Live weapon metadata

1. Что исследовано: actual loaded catalog in original TI after B9 delivery.
2. Что доказано:300/301/326 type1, equipable1; weaponType2/3/2.0/1/2 type0.
3. Новые packet mappings: none.
4. Новые структуры: bounded read-only metadata snapshot id+116/type+118/weaponType+120/equipable+68d.
5. Изменённые файлы: capture_loaded_orange.py, live log/summary/test database, NEXT_TASK.md.
6. Добавленные тесты:12-second live trial exit0, no Frida errors.
7. Что остаётся неизвестным: authoritative equip mutation and slot response.
8. Риски и альтернативы: standalone variant comparison lacked initialized runtime; live snapshot replaces that detour for current catalog. No visual/equip claim.
9. Следующий самый полезный шаг: server equipment action and live inventory model update.

## 2026-09-12 — Atomic equipment persistence

1. Что исследовано: owned_pets snapshot storage and inventory fields.
2. Что доказано: assign/move/replace/remove persist atomically; ownership rejection and database rollback preserve snapshots.
3. Новые packet mappings: no new route; uses existing ItemList serialization.
4. Новые структуры: EquipmentStore with required explicit template/slot rules.
5. Изменённые файлы: tio/equipment.py, tests/test_equipment.py, NEXT_TASK.md.
6. Добавленные тесты:4 persistence tests;146 total PASS.
7. Что остаётся неизвестным: production compatibility/automatic selection, client live response.
8. Риски и альтернативы: test rule301:(10,80) is not production evidence; no guessed compatibility activated. Replacement returns displaced item to backpack as service behavior.
9. Следующий самый полезный шаг: connect confirmed production rules and33 handler, verify30 live update.

## 2026-09-12 — Live persisted equipment snapshot

1. Что исследовано: EquipmentStore output through original inventory consumer.
2. Что доказано: separate trial DB assigned1001 to mask16; live30 consumer returns equipped1/slot16/template301.
3. Новые packet mappings: existing30 accepts equipped snapshot.
4. Новые структуры: read-only snapshot logging includes equipped/slot.
5. Изменённые файлы: capture_loaded_orange.py, trial DB/log/summary, NEXT_TASK.md.
6. Добавленные тесты:12-second original TI run, exit0/noFrida errors, matching item model.
7. Что остаётся неизвестным: valid weapon slot rules/automatic selection,33 route and visual equip behavior.
8. Риски и альтернативы: diagnostic explicit16 acceptance is not proof of compatibility; no production rule activated.
9. Следующий самый полезный шаг: wire33 with recovered rules and native action live roundtrip.

## 2026-09-12 — Primary weapon request route

1. Что исследовано: PrimaryWeapon RTTI and existing slot/model evidence.
2. Что доказано: a81bf9 method pointer a84398 reads model+df0, primary slot16; service tests persist33 requests.
3. Новые packet mappings:33 route for current301/326 ->30 snapshot, errors via existing error reply.
4. Новые структуры: equip_primary_weapon service entry.
5. Изменённые файлы: equipment.py, loopback_exchange.py, test_equipment.py, NEXT_TASK.md.
6. Добавленные тесты: primary optionFF/4, unsupported7 leaves snapshot unchanged;147 total PASS and launcher module compile.
7. Что остаётся неизвестным: full live request roundtrip, additional slots/unequip behavior.
8. Риски и альтернативы: FF choosing primary is explicit local emulator policy, not original server recovery. Repeated requests assign idempotently. Only two current weapons supported.
9. Следующий самый полезный шаг: original9903a4 ->server33 ->client30 live probe.

## 2026-09-12 — Live equipment request roundtrip

1. Что исследовано: original9903a4 request through local server and original990638 response.
2. Что доказано:33(1,1001,FF) saved; client changed equipped0/slot0 to1/16; reopened SQLite matches.
3. Новые packet mappings:33 ->30 primary assignment live confirmed.
4. Новые структуры: bounded --probe-equip uses separateDB and one-shot native builder call.
5. Изменённые файлы: run_reservation.py, capture_loaded_orange.py, trialDB/log/summary, NEXT_TASK.md.
6. Добавленные тесты:12-second live exit0/noFridaerrors;147 unit PASS.
7. Что остаётся неизвестным: manual UI action, unequip request, additional slots.
8. Риски и альтернативы: automatic primary default is local policy; native builder call is diagnostic, not UI evidence.
9. Следующий самый полезный шаг: actual unequip callback and durable remove/replace loop.

## 2026-09-12 — Equip and remove cycle

1. Что исследовано: equipment widget DoMouseDoubleClick a4dba0 and both item states.
2. Что доказано: native callback passes same pet/item/null target for equipped0/1. Live two original33FF requests change client0/0 ->1/16 ->0/0; final DB matches.
3. Новые packet mappings:FF now toggles current city weapon; explicit4 stays assignment.
4. Новые структуры: atomic toggle option in EquipmentStore.
5. Изменённые файлы: equipment.py, tests, native verifier, capture/launcher, evidence.
6. Добавленные тесты: native2cases, toggle/idempotent explicit target unit, live12s cycle;148 unit PASS.
7. Что остаётся неизвестным: physical UI clicks, other equipment slots, full city functionality.
8. Риски и альтернативы: server toggle semantic inferred from shared client double-click action, not original server trace. Explicit targets remain idempotent.
9. Следующий самый полезный шаг: display of equipped items and replacement, then broader city functions.

## 2026-09-12 — Primary model and replacement

1. Что исследовано: original pet model+df0 after inventory responses, two-weapon replacement.
2. Что доказано: model300->301->326->300; displaced item returns backpack, both IDs preserved, final SQLite agrees. Wallet9900/10000 after one100-credit purchase.
3. Новые packet mappings: no new opcodes; existing33/30 cycle confirmed for replacement.
4. Новые структуры: primary model snapshot fields and --probe-equip-replace.
5. Изменённые файлы: capture_loaded_orange.py, run_reservation.py, test DB/logs/summaries.
6. Добавленные тесты: two live12s runs and148 unit PASS.
7. Что остаётся неизвестным: physical UI/render, other slots, full arena and city functions.
8. Риски и альтернативы: native diagnostic sender, no screenshot claim. Initial replacement setup lacked second item due Path argument error; corrected after process exit and retained setup-only log.
9. Следующий самый полезный шаг: broader city gameplay or manual UI verification.

## 2026-09-12 — Arena loading lifecycle

1. Что исследовано: ArenaService waiting-room state and existing Start/loaded codecs.
2. Что доказано: owner-only Start, preparation failure leaves state unchanged, duplicate starts/acks suppressed and disconnect clears loading.
3. Новые packet mappings: service-level36->37 after start; transport not connected yet.
4. Новые структуры: per-room loading member set, prepared scene callback.
5. Изменённые файлы: arena_service.py, test_arena_service.py, NEXT_TASK.md.
6. Добавленные тесты:2 lifecycle tests;150 total PASS.
7. Что остаётся неизвестным: routed start scene, complete combat and turns.
8. Риски и альтернативы: state describes loading only, not battle readiness or combat completion. Scene assets remain preparer responsibility.
9. Следующий самый полезный шаг: Start2E transport integration and original client roundtrip.

## 2026-09-12 — Start loading roundtrip

1. Что исследовано: original Start builder a08ab0, service loading and acknowledgements.
2. Что доказано: live2E ->35/3B/41 ->36 ->37, scene4 and actor1 HP100.
3. Новые packet mappings: transport routes2E/36 through ArenaService.
4. Новые структуры: diagnostic scene preparer on Start instead of Create.
5. Изменённые файлы: loopback_exchange.py, capture_loaded_orange.py, live evidence.
6. Добавленные тесты: live12s exit0/noFrida errors;150 unittest PASS.
7. Что остаётся неизвестным: playable scene/combat/turns, normal Start generation and UI clicks.
8. Риски и альтернативы: scene remains explicit diagnostic mode; normal Start rejects with message. Log parser corrected to packets_hex for C2S.
9. Следующий самый полезный шаг: battle state beyond loading and client turn protocol.

## 2026-09-12 — EndTurn request

1. Что исследовано: SND_ENDTURN action and95e08c.
2. Что доказано: original3A writes actor ID, zero fallback, own/flag scan, disabled/deadline gates and deadline+30000.
3. Новые packet mappings: C2S3A u32actorID.
4. Новые структуры: strict EndTurn codec.
5. Изменённые файлы: battle_turn.py, native verifier, tests, evidence.
6. Добавленные тесты: native6cases, codec fixtures/truncation;152tests.
7. Что остаётся неизвестным: server next-turn notification and combat state.
8. Риски и альтернативы: eligibility predicate94ca14 isolated; no combat or route claim. Clock units not independently verified.
9. Следующий самый полезный шаг: incoming turn state before implementing3A mutation.

## 2026-09-12 — YourTurn messages

1. Что исследовано: dispatcher96244c and95e1e0.
2. Что доказано:38 carriesu32seconds; callback sets authenticated local character as turn owner, timer call and gateclock+500.
3. Новые packet mappings: S2C38 duration,39 finished no body.
4. Новые структуры: turn codecs.
5. Изменённые файлы: battle_turn.py, native verifier/tests/evidence.
6. Добавленные тесты: native3 duration cases,153unit PASS.
7. Что остаётся неизвестным: live turn activation and full turn state.
8. Риски и альтернативы: notifications/timer setter/UI isolated; no playable combat claim.
9. Следующий самый полезный шаг: live38 after loading acknowledgement and3A response.

## 2026-09-12 — Live turn cycle

1. Что исследовано:38/3A/39 original client cycle.
2. Что доказано: enabled1 ->originalEndTurn ->server39 ->enabled0, no Frida errors, exit0.
3. Новые packet mappings: routed3A with server owner/actor validation.
4. Новые структуры: per-room active turn, server-supplied actor IDs.
5. Изменённые файлы: arena_service.py, loopback/capture, tests, live evidence.
6. Добавленные тесты: lifecycle authorization assertions and live12s;153total PASS.
7. Что остаётся неизвестным: timer enforcement, rotation, battle actions and UI.
8. Риски и альтернативы: one diagnostic turn, not complete combat; IDs supplied by scene caller.
9. Следующий самый полезный шаг: authoritative turn deadlines and actor actions.

## 2026-09-12 — Authoritative turn timeout

1. Что исследовано: server turn lifetime and socket polling.
2. Что доказано: exact deadline rejects lateEndTurn, expiration once; live2s timeout sends39, clientenabled0, noC2S3A.
3. Новые packet mappings: existing39 used for server timeout.
4. Новые структуры: monotonic deadline per turn, addressed expire_turns replies.
5. Изменённые файлы: service, transport, capture/launcher timeout probe, tests/evidence.
6. Добавленные тесты: boundary/early-end expiry unit and live12s;154total PASS.
7. Что остаётся неизвестным: actor actions, multiplayer rotation and full combat.
8. Риски и альтернативы: timeout delivery bounded by0.5s polling; diagnostic duration2s.
9. Следующий самый полезный шаг: movement/action protocol and authoritative validation.

## 2026-09-12 — Actor coordinate request

1. Что исследовано:95e114 and caller9b8008.
2. Что доказано: original46 actor:u32/x:u8/y:u8 with disabled gate; caller uses model coordinates.
3. Новые packet mappings: C2S46 structural codec only.
4. Новые структуры: BattlePositionRequest.
5. Изменённые файлы: battle_position.py, native verifier/tests/evidence.
6. Добавленные тесты:3native cases, fixture/malformed unit;156total PASS.
7. Что остаётся неизвестным: movement vs stop/action semantics and server response.
8. Риски и альтернативы: current-position caller prevents assuming movement directly; no mutation route added.
9. Следующий самый полезный шаг:95d41a caller and incoming actor position update.

## 2026-09-12 — Coordinate request same-cell gate

1. Что исследовано: original95d39c caller and real x87 distance helper a8907c.
2. Что доказано: mode5 and selected actor required; same tile sends46, adjacent/diagonal/far tiles do not. Helper computes rounded Euclidean distance; 3/4 delta returns5.
3. Новые packet mappings: none;46 semantics remain UNKNOWN.
4. Новые структуры: native gate evidence with target, mode, selection, distance and writer arguments.
5. Изменённые файлы: tools/verify_battle_position_gate_native.py, evidence/battle_position_gate_native.json, NEXT_TASK.md, WORK_REPORT.md.
6. Добавленные тесты:7 native cases PASS; no production changes, unit suite not rerun.
7. Что остаётся неизвестным: actual movement opcode/response, other46 caller intent.
8. Риски и альтернативы: selected actor lookup and outbound writer isolated; real geometry executed. This proves only this caller's gate, not UI behavior or universal46 intent.
9. Следующий самый полезный шаг: inspect95ba7c/958710 actions from95da9c and other46 caller9b8008; identify actual movement before routing mutations.

## 2026-09-12 — Target request and inventory action distinction

1. Что исследовано:95ba7c ->95b8bc ->9595f0, second46 caller9b7f50.
2. Что доказано: original C8/3D serializer writes fouru32;3 marker cases pass with real writers. Static46 caller is reached after window_inventory action and queries current-cell array.
3. Новые packet mappings: C2S C8/3D structural only, actor/unknown/x/y; action semantics unresolved.
4. Новые структуры: native target request evidence.
5. Изменённые файлы: tools/verify_battle_target_request_native.py, evidence/battle_target_request_native.json, NEXT_TASK.md, WORK_REPORT.md.
6. Добавленные тесты:3 native serializer cases PASS, including high bits and coordinates beyond255. No production change; unit suite not rerun.
7. Что остаётся неизвестным: C8/3D second field and action, actual movement request.
8. Риски и альтернативы: begin/end transport isolated. window_inventory is evidence for inventory context, not full46 semantics or UI proof.
9. Следующий самый полезный шаг: trace movement mode/action selection rather than treating arbitrary coordinate packets as movement.

## 2026-09-12 — Known mines packet

1. Что исследовано: action selection9c02f4, network serializer658bc8, RTTI623d08/623af2.
2. Что доказано: C8/3E is TANetSendKnownMinesList; countu32 followed by x/y/itemId/team u32 fields. Original serialization of empty, one and two entries matches codec.
3. Новые packet mappings: C8/3E known mines list CONFIRMED; C8/3D mine-action hypothesis remains unconfirmed.
4. Новые структуры: KnownMine and bounded known-mines codec.
5. Изменённые файлы: tio/protocol/known_mines.py, tools/verify_known_mines_native.py, tests/test_known_mines.py, evidence/known_mines_native.json, progress docs.
6. Добавленные тесты:3 native cases with no writer stubs; fixture and malformed/oversize tests;158 total unit tests PASS.
7. Что остаётся неизвестным: mine request semantics, receiver lifecycle and actual movement request.
8. Риски и альтернативы: serializer proof does not establish live handling or mine mechanics. No speculative production routing. RECV_Move725454 is flag setter, not packet parser; mode1 actor selection is not proven movement.
9. Следующий самый полезный шаг: locate known-mines consumer for empty map initialization, then actual battle action request handling.

## 2026-09-12 — Live empty known-mines initialization

1. Что исследовано: dispatcher95cbf4 ->queued95c748 ->658b00 and reader658b7c.
2. Что доказано: live C8/3E empty list parsed count0, original receiver returned, scene finalized4, turn finished enabled0. Process exit0, no Frida errors.
3. Новые packet mappings: existing C8/3E now sent during diagnostic scene preparation before41.
4. Новые структуры: parsed-count and receiver-return diagnostic events.
5. Изменённые файлы: tools/loopback_exchange.py, tools/capture_loaded_orange.py, live evidence and progress docs.
6. Добавленные тесты: separate SQLite12s live run; all158 unit tests PASS.
7. Что остаётся неизвестным: nonempty list rendering, deployment/disarm, movement and full combat.
8. Риски и альтернативы: instrumented scene only; main database untouched. No manual UI proof or mine mechanics claim.
9. Следующий самый полезный шаг: actual battle movement request and authoritative actor actions.

## 2026-09-12 — Battle movement response

1. Что исследовано: ti.exe BattleSoldierMove error reference6dc641 ->reader6dc600, dispatcher6dd34c.
2. Что доказано: opcode3D actoru32/countu8/coordinate byte pairs; original path reader consumes exact body and writes final coordinates at actor+1cc/+1d0. Empty path preserves coordinates.
3. Новые packet mappings: S2C3D BattleSoldierMove CONFIRMED structural and scene model writes.
4. Новые структуры: BattleMove codec.
5. Изменённые файлы: tio/protocol/battle_move.py, tools/verify_battle_move_native.py, tests/test_battle_move.py, evidence/battle_move_native.json, progress docs.
6. Добавленные тесты:4 native paths including empty/multiple/boundary; malformed path tests;160 unit tests PASS.
7. Что остаётся неизвестным: outbound movement request, silver model consumer, live animation and server rules.
8. Риски и альтернативы: native actor lookup and UI/animation isolated, final notification skipped, execution stops before cleanup. No playable movement claim.
9. Следующий самый полезный шаг: silver3D consumer and outbound request, then authoritative actor action and live movement response.

## 2026-09-12 — Live battle movement response

1. Что исследовано: full original3D client execution after scene loading and turn activation.
2. Что доказано: initial actor2,2 ->path3,2/4,2 ->silver model4,2 and ti scene4,2; receiver returned, turn finished, exit0/noFridaerrors.
3. Новые packet mappings: existing3D now exercised in live diagnostic session.
4. Новые структуры: movement diagnostic event comparing model/scene coordinates.
5. Изменённые файлы: tools/run_reservation.py, tools/capture_loaded_orange.py, tools/loopback_exchange.py, live evidence and progress docs.
6. Добавленные тесты:12s separate-database live response;160 unit tests PASS.
7. Что остаётся неизвестным: C2S movement request, server ownership/turn/path/action-point validation and actual UI movement.
8. Риски и альтернативы: server injects diagnostic route only with --probe-battle-move. Original receiver is full/unmodified, but no player-click or complete movement claim.
9. Следующий самый полезный шаг: find ti.exe outbound sender and implement authoritative movement state/action handling.

## 2026-09-12 — Original movement request

1. Что исследовано: ti.exe calls to transport718e68/71944c ->6dc460.
2. Что доказано: original sender writes3C, actoru32, countu8 and xy byte pairs; selected path copied from int32 pairs. Disabled global76e224 prevents send.
3. Новые packet mappings: C2S3C movement request structural CONFIRMED, complementary S2C3D already live verified.
4. Новые структуры: encode/decode_move_request using BattleMove body.
5. Изменённые файлы: tio/protocol/battle_move.py, tools/verify_move_request_native.py, tests/test_battle_move.py, evidence/move_request_native.json, progress docs.
6. Добавленные тесты:4 native sender cases with real writers, request fixture/malformed cases;161 unit tests PASS.
7. Что остаётся неизвестным: server action-point rules and actual input roundtrip.
8. Риски и альтернативы: transport and critical sections isolated. Sender uses fixed local output buffer; large native probe arrays must not be used. No3C server route yet.
9. Следующий самый полезный шаг: authoritative position/turn/path validation and3C->3D live roundtrip via original sender.

## 2026-09-12 — Authoritative movement validation

1. Что исследовано: arena lifecycle and current3C/3D codecs.
2. Что доказано: accepted paths update position and deduct explicit cost; rejected owner/turn/deadline/nonadjacent/outside/blocked/occupied/corner/AP requests leave state unchanged in tests.
3. Новые packet mappings: no new mapping; service accepts3C and returns3D, transport not connected yet.
4. Новые структуры: immutable BattleActor, BattleField, per-room fields attached after loading starts.
5. Изменённые файлы: tio/battle_state.py, tio/arena_service.py, tests/test_battle_state.py, progress docs.
6. Добавленные тесты: movement budget, atomic rejection cases, lifecycle/deadline/disconnect;164 unit tests PASS.
7. Что остаётся неизвестным: original movement costs, AP client update, input route and multiplayer turn rotation.
8. Риски и альтернативы: movement costs and blocked cells supplied by server explicitly; local rules are not recovered original balance. No transport/live3C roundtrip yet.
9. Следующий самый полезный шаг: configure field, route3C, invoke original sender for live3C->3D and verify AP state.

## 2026-09-12 — Movement request roundtrip

1. Что исследовано: native6dc460 sender through existing transport into ArenaService.move.
2. Что доказано: live3C request accepted once,3D response updates both client coordinates4,2; server AP40->38 and position4,2; turn ends, retry exit0/noFridaerrors.
3. Новые packet mappings:3C now routed to authoritative movement service, returns3D.
4. Новые структуры: diagnostic field initialized after Start (empty8x8, actor2,2, AP40, step_cost1); accepted-state event.
5. Изменённые файлы: tools/loopback_exchange.py, tools/capture_loaded_orange.py, live logs/database/summary and progress docs.
6. Добавленные тесты:12s original sender live roundtrip;164unit tests PASS.
7. Что остаётся неизвестным: client AP synchronization, original costs, manual path click and turn rotation.
8. Риски и альтернативы: first small executable allocation run ended before request; fullpage allocation fixed observed failure on retry. Native sender is diagnostic invocation; no manual UI claim. LocalAP40/cost1 is explicit test profile.
9. Следующий самый полезный шаг: recover AP update response and synchronize remaining AP; then repeated/invalid live actions and UI.

## 2026-09-12 — Action points synchronization

1. Что исследовано: TANetStatusUpdate4E serializer654f38, attribute10 branch8c7320/8c7947.
2. Что доказано: native values0/38/255 serialize and write ownactor+6004. Live movement4E update returns full8c82b0; clientAP38 equals serverAP38; exit0/noFridaerrors.
3. Новые packet mappings:4E actoru32/countu32/(statusu32,valueu32)/optional-effect-byte, narrow status10 encoder.
4. Новые структуры: encode_action_points; battle actor AP bounded0..255 to match client.
5. Изменённые файлы: protocol/action_points.py, battle_state.py, loopback/capture, native verifier/unit tests and live evidence.
6. Добавленные тесты:3native cases, fixture/range test,12s live;165unit tests PASS.
7. Что остаётся неизвестным: initialAP alignment, original cost/maxAP balance, manual UI and rotation.
8. Риски и альтернативы: UI not visually checked. Native isolated status branch used before live full handler. Only ownactor AP update supported.
9. Следующий самый полезный шаг: align initialAP with server before input and verify repeated/invalid actions then UI.

## 2026-09-12 — Initial AP and repeated movement

1. Что исследовано: initial loaded->turn sequence and movement after rejection.
2. Что доказано: live initialAP40 callback precedes YourTurn; valid/invalid/valid original requests produce AP38/unchanged/37; exactly two accepts and one nonadjacent-path rejection, turn finishes, exit0/noFridaerrors.
3. Новые packet mappings: existing4E now sent from authoritative field before first38.
4. Новые структуры: diagnostic sequence of three original movement requests.
5. Изменённые файлы: tools/loopback_exchange.py, tools/capture_loaded_orange.py, movement_sequence live evidence and progress docs.
6. Добавленные тесты:12s separateDB live sequence;165unit tests PASS.
7. Что остаётся неизвестным: physical UI path selection, original AP balance, turn rotation and full city gameplay.
8. Риски и альтернативы: diagnostic native sender invocation, no physical mouse claim. AP40/cost1 remains explicit local profile.
9. Следующий самый полезный шаг: physical UI interaction and arena turn lifecycle beyond one diagnostic turn.

## 2026-09-12 — Next-turn budget restoration

1. Что исследовано: repeated begin_turn lifecycle and server field ownership.
2. Что доказано: unit second turn restores original local AP budget, preserves position; already-active/foreign/unknown selection cannot refill AP or create a turn.
3. Новые packet mappings: none; begin_turn_packets orders existing4E then38.
4. Новые структуры: peractor initial turn budget, atomic selection validation and refill.
5. Изменённые файлы: tio/battle_state.py, tio/arena_service.py, tools/loopback_exchange.py, tests/test_battle_state.py, progress docs.
6. Добавленные тесты: full-selection rejection and repeated turn lifecycle;167unit tests PASS.
7. Что остаётся неизвестным: original AP regeneration rules, multiplayer recipient routing and automatic turn rotation.
8. Риски и альтернативы: explicit local full-refill rule, not original balance. No live second-turn claim; scheduler not connected.
9. Следующий самый полезный шаг: turn scheduling after end/timeout and live multiple-turn verification.

## 2026-09-12 — Turn rotation service

1. Что исследовано: end/expiration state and recipient-specific turn activation.
2. Что доказано: two-owner unit fixture17->99 after end,99->17 after deadline; rejected off-turn movement, AP refill only next owner, repeated expiry suppressed, owner-disconnect cleanup.
3. Новые packet mappings: none; addressed4E/38 returned from advance_turn.
4. Новые структуры: last completed turn per room; actor IDs by owner; local circular member ordering.
5. Изменённые файлы: tio/battle_state.py, tio/arena_service.py, tests/test_battle_state.py, progress docs.
6. Добавленные тесты: two-owner transition fixture;168unit tests PASS.
7. Что остаётся неизвестным: original initiative/death eligibility and live multiplayer delivery.
8. Риски и альтернативы: rotation policy is local; join records set in fixture, no live two-client claim. Transport scheduler not wired.
9. Следующий самый полезный шаг: addressed delivery integration and live multiple-turn verification.

## 2026-09-12 — Live consecutive turns

1. Что исследовано: end39 ->advance_turn ->AP40/YourTurn38 ->second native movement cycle.
2. Что доказано: two full turns in original client; AP40/38/37 twice, four accepted routes and two rejected jumps, final2,2/AP37, two finish callbacks, exit0/noFridaerrors.
3. Новые packet mappings: none; addressed next-turn replies delivered to sole diagnostic participant.
4. Новые структуры: --probe-two-turns bounded second-turn flag; path relative to current position.
5. Изменённые файлы: run_reservation.py, capture_loaded_orange.py, loopback_exchange.py, live evidence and progress docs.
6. Добавленные тесты:12s separateDB live two-turn run;168unit tests PASS.
7. Что остаётся неизвестным: real multiplayer transport/join, physical UI, full combat and default gameplay.
8. Риски и альтернативы: exactly two diagnostic turns of one participant; no claim of two-client multiplayer or default automatic rotation.
9. Следующий самый полезный шаг: physical UI/default arena access or multi-session turn delivery, preserving full city scope.

## 2026-09-12 — UI observation and disconnect rotation

1. Что исследовано: normal city launch with computer-use @oai/sky; first-turn guest departure.
2. Что доказано: two list_windows observations had no TI target window; no UI actions made. Guest departure on first active turn previously lost rotation cursor; fixed and tested next owner activation.
3. Новые packet mappings: none.
4. Новые структуры: preserve departing active guest as last turn owner in surviving room.
5. Изменённые файлы: tio/arena_service.py, tests/test_battle_state.py, city_ui_check evidence and progress docs.
6. Добавленные тесты: first guest turn/disconnect/advance and departed actor rejection;169unit tests PASS.45s city process exit0.
7. Что остаётся неизвестным: cause of missing targetable UI window, multi-client delivery and actor removal upon disconnect.
8. Риски и альтернативы: no physical UI verification. Goal remains actionable through server implementation; no global blocker claimed.
9. Следующий самый полезный шаг: diagnose visible client window or finish disconnect actor notifications and gameplay actions.

## 2026-09-12 — Actor removal, arena observations, city priority

1. Что исследовано: silver8c71e0 removal43, guest disconnect, original85decc mode ranges, ground.xml dependencies; updated user city scope.
2. Что доказано: original removal reader consumes u32 and writes removed1/xy255; full live callback returns. Village24 brush files present, current scene8x8 empty. Native mode4 callback forces8 players and1 soldier; UI setter/predicate isolated.
3. Новые packet mappings: S2C43 actor:u32; native and live evidence. No attack/warehouse/skill mapping inferred.
4. Новые структуры: remove_owner releases actors and AP budgets; disconnect_packets addressed surviving members; separateDB removal diagnostic.
5. Изменённые файлы: battle_state.py, arena_service.py, battle_remove.py, test_battle_state.py, three launcher/transport tools, native verifiers and evidence.
6. Добавленные тесты: owner removal frees occupied path; idempotence; strict43 body;171unit PASS; removal3native cases, mode9native cases, live18s exit0.
7. Что остаётся неизвестным: scene rendering artifacts/visual removal, original complete mode limits, real multiplayer delivery. City warehouse and mercenary skill operations absent from current server.
8. Риски и альтернативы: screenshot proves partial ground, not missing all textures. Diagnostic scene not production arena. Previous removal_live.log ran before route edit; retry log authoritative.
9. Следующий самый полезный шаг: per updated goal, city hiring/shop/warehouse/equipment/skills; pause arena expansion.

## 2026-09-12 — City warehouse protocol

1. Что исследовано: TANetWarehouseList RTTI61441a, Write6146b6->63f60c, item63ead4, RECV_WarehouseList993930->63f4f4.
2. Что доказано: original serializers emit6A,typeu32,segmentCountu16,segmentu16,countu32 then ordinary item records. Three cases execute original writers with only managed cleanup isolated.
3. Новые packet mappings: S2C6A warehouse list. No request or item transfer mapping established.
4. Новые структуры: WarehouseItem instance/template/count, three durability values, two enhancement bytes, three booleans; optional name/time/gift absent. Segment index base remains unknown.
5. Изменённые файлы: tio/protocol/warehouse.py, tools/verify_warehouse_native.py, tests/test_warehouse.py and evidence.
6. Добавленные тесты: native empty/one/multiple records; exact native wire bytes, segmented codec, all truncations, invalid opcode/boolean/optional/trailing bytes;174unit PASS.
7. Что остаётся неизвестным: client request, transfer command, segment numbering, optional gift contents; warehouse persistence and transport not implemented.
8. Риски и альтернативы: codec does not restore warehouse UI by itself; unsupported optional data rejected explicitly, not silently lost.
9. Следующий самый полезный шаг: recover original warehouse request/transfer and connect persistent owned inventory without item duplication.

## 2026-09-12 — Correct shop versus warehouse routing

1. Что исследовано: warehouse manager915074 calls9921a8, nested992178; shop991940; transfer candidate992294.
2. Что доказано: original builders send69+warehouse byte and73+shop category respectively. Six native cases pass. Live corrected shop request invokes original list74 handler to completion, exit0.
3. Новые packet mappings: CORRECTION prior69->74 was wrong. Correct73->74;69 expects warehouse6A. Transfer6B body direction still unverified.
4. Новые структуры: no new persistence. Native force flag bypasses request-cache checks only; transport/UI bookkeeping isolated.
5. Изменённые файлы: city_services.py, test_city_catalogs.py, capture_loaded_orange.py, README.md, CITY_SERVICES.md, new verify_city_requests_native.py and evidence.
6. Добавленные тесты: warehouse request cannot produce shop catalog; existing shop tests corrected;174unit PASS. Live catalog probe now explicitly invokes original991940 using full-page thunk.
7. Что остаётся неизвестным: warehouse segmentation base, item transfer direction, persistent warehouse and its UI roundtrip.
8. Риски и альтернативы: historical claims69->74 are superseded. Warehouse remains unhandled rather than receiving unrelated shop data. Live callbacks do not prove visible UI correctness.
9. Следующий самый полезный шаг: recover6B arrays/direction from caller, implement atomic warehouse/inventory transfer and6A snapshots.

## 2026-09-12 — Warehouse transfer array format

1. Что исследовано: original992294, caller list at a66221/993f9f; native model stride656/id+28/count+1c.
2. Что доказано:6B kind byte, actoru32, two counted arrays of id/countu32 pairs. ECX supplies first, stack argument second. Original serializer passes empty/first-only/second-only/asymmetric-both cases.
3. Новые packet mappings: C2S6B structural codec, direction deliberately unnamed pending caller evidence.
4. Новые структуры: WarehouseTransfer first_items and second_items preserve ordered arrays; no inventory mutations.
5. Изменённые файлы: warehouse_transfer.py, verify_warehouse_transfer_native.py, test_warehouse_transfer.py and evidence.
6. Добавленные тесты: native4 cases; exact wire example, asymmetric arrays, all truncations/bad count/opcode/trailing data.176unit PASS.
7. Что остаётся неизвестным: which array deposits/withdraws, segmentation and large native batching, response sequence and persistence.
8. Риски и альтернативы: actual native array length helper executes; only refcount, transport acquisition/flush and UI bookkeeping isolated. Batch boundaries not verified. No live transfer claim.
9. Следующий самый полезный шаг: trace b76e04/b76e08 assignments in UI to establish source/destination then implement atomic persisted transfer.

## 2026-09-12 — Warehouse UI direction evidence

1. Что исследовано: a6650d/a6653e source type0 ->target3/12/16/17; reverse brancha66725; globalsb76e04/b76e08.
2. Что доказано: nativea66645 populates first array only; nativea667b2 populates second only; both reach992294 actor17/kind0/item1001 in correct argument. Type3 default kind0,12->1,16->2,17->3 by explicit branches.
3. Новые packet mappings: none;6B direction strengthened but not yet wired.
4. Новые структуры: first array corresponds widget0->warehouse family; second reverse. Deposit/withdraw naming is strong inference until widget0 identity independently established.
5. Изменённые файлы: tools/verify_warehouse_ui_arrays_native.py, evidence and progress docs.
6. Добавленные тесты: two original UI branch executions; managed allocation/clear/copy isolated, actual branch argument placement executed. Existing176unit status unchanged; production code not changed.
7. Что остаётся неизвестным: independent widget0 identity, response sequencing, persistence, live transfer.
8. Риски и альтернативы: synthetic widgets and entering below outer checks are not a physical drag/drop test or proof of all validation gates.
9. Следующий самый полезный шаг: confirm widget0 inventory identity, then atomically persist deposit/withdraw and authorize6B against saved ownership.

## 2026-09-12 — Persistent private warehouse

1. Что исследовано: existing OwnedPetStore/ItemList persistence and transaction boundaries.
2. Что доказано: explicit deposit/withdraw/exchange saves both locations atomically; exact item data restored after roundtrip; replay concurrency produces one success, one rejection.
3. Новые packet mappings: none;6B routing remains pending UI identity/response mapping.
4. Новые структуры: warehouse_items(account,instance_id,item_packet), WarehouseStore with explicit capacity. ItemList owner0 is internal storage envelope only, not a claimed wire warehouse response.
5. Изменённые файлы: tio/warehouse.py, tests/test_warehouse_store.py and progress docs.
6. Добавленные тесты: exchange at capacity, reopen, ownership/quantity/duplicates/capacity/equipped rejection, injected insert failure rollback, concurrent replay;181unit PASS.
7. Что остаётся неизвестным: original capacity policy, partial-stack ID allocation, response sequence, live UI transfer.
8. Риски и альтернативы: whole instances/stacks only; explicit operations not yet reached by client requests. No changes to primary character DB. Account-wide duplicate IDs rejected before mutation.
9. Следующий самый полезный шаг: establish inventory widget identity/6B direction, project stored records to6A without discarding fields, route and verify original client roundtrip.

## 2026-09-12 — Saved warehouse item projection

1. Что исследовано: ItemListElement RTTI611ff0 compared WarehouseListItem613bc0 and original serializers63befc/63ead4.
2. Что доказано: fields map by native names/order; persisted marked/rented/enhanced item projects to6A and withdraws with exact original ItemList bytes.
3. Новые packet mappings:6A optional markTimeLeft flag/u32 now supported; marker names/gifts still explicitly unsupported.
4. Новые структуры: warehouse_item_from_inventory; warehouse mark_time_left optional. Persistent records preserve inventory-only fields absent from6A.
5. Изменённые файлы: protocol/warehouse.py, verify_warehouse_native.py, test_warehouse_store.py and evidence.
6. Добавленные тесты: enhanced/marked/rented saved roundtrip and projection; native serializer optional time123456;182unit PASS.
7. Что остаётся неизвестным: segmentation numbering, response sequence, live warehouse integration, stack splitting and full optional gift/name branches.
8. Риски и альтернативы: projection is not used to reconstruct ItemRecord, so battery/type/trimmed enhancement are retained in original storage. No primary DB edits.
9. Следующий самый полезный шаг: warehouse response segmentation/receiver and live69->6A, then6B transfer route with ownership validation.

## 2026-09-12 — Personal warehouse end-to-end transport

1. Что исследовано: original segment consumer992598, zero-based reset/final behavior; private request69 and transfer6B integration. User narrowed active goal to fully working personal warehouse.
2. Что доказано: live saved snapshot69->6A applied; original992294 withdrawal/deposit produces two committed transfers and three successful warehouse list callbacks. Final saved item1001 only in warehouse; empty merc inventory; wallet10000/10000; exit0/noFrida errors.
3. Новые packet mappings:69 00 returns saved private6A;6B type0 first deposits/second withdraws, returns30 inventory then6A full snapshot. Nonprivate mutation rejected.
4. Новые структуры: encode_private_warehouse_snapshot segmented200; read-only Store omitscapacity, mutations requireexplicitcapacity. Local configurable100-slot policy. transfer_private_items binds protocol and store.
5. Изменённые файлы: warehouse.py, warehouse_service.py, protocol/warehouse.py, city_catalogs.py/json, loopback_exchange.py, capture_loaded_orange.py, run_reservation.py, tests and evidence.
6. Добавленные тесты: segmented empty/multi snapshot and readonly protection, wire transfer updates both lists/nonprivate rejection;184unit PASS. Live12s isolatedDB roundtrip.
7. Что остаётся неизвестным: physical UI interaction, full stack splitting, capacity UI/original policy alignment, optional gift/name support. Goal not complete.
8. Риски и альтернативы: native request probe constructs model arrays programmatically, no physical drag claim. Snapshot validated before transaction commit. User main DB untouched by diagnostic.
9. Следующий самый полезный шаг: implement partial-stack transfers with transaction-safe IDs; verify warehouse through visible UI and relog, align displayed capacity and error feedback.

## 2026-09-12 — Partial warehouse quantities

1. Что исследовано: WarehouseStore quantity restriction and shop item_sequences allocator.
2. Что доказано: partial deposit/withdraw preserves sum and all item metadata; source ID retains remainder, destination receives new shared ID. Full deposits advance sequence even without splitting, preventing reuse by shop.
3. Новые packet mappings: none; existing6B count is now applied partially.
4. Новые структуры: transaction-scoped split allocation; warehouse UPSERT handles remainder changes; capacity only subtracts full withdrawals.
5. Изменённые файлы: tio/warehouse.py, tests/test_warehouse_store.py and progress docs.
6. Добавленные тесты: partial both directions/reopen, quantity conservation/metadata, partial withdrawal does not free slot, failure rolls back quantity and sequence, whole deposit reserves ID;188unit PASS.
7. Что остаётся неизвестным: native partial-transfer UI behavior, quantity dialog, displayed capacity, relog UX, marker name/gift fields.
8. Риски и альтернативы: partial repeated requests can legitimately consume remaining quantity; no wire transaction token exists in recovered request. No claims of replay idempotence for partially fulfilled source. Automatic stack merging not introduced.
9. Следующий самый полезный шаг: live native partial transfer with stackable catalog item, then physical warehouse UI/capacity/relog verification.

## 2026-09-12 — Live partial ammunition transfer

1. Что исследовано: items.cfg template3 Ammo9mm stackable1/packamount50; loadera733b5 and native transfer probe.
2. Что доказано: actual client992294 emits partial withdrawal3/deposit2; server saves both, client applies three warehouse snapshots. Reopened DBwarehouse7+2/inventory1, total10, unique instance IDs, exit0/noFridaerrors.
3. Новые packet mappings: none; existing6B quantity and30/6A responses verified with splits.
4. Новые структуры: --probe-warehouse-partial; catalogsourceammo3 with originalstackable/packamount/itype/weight fields.
5. Изменённые файлы: build_item_fixture.py, generatedXML/provenance, run_reservation.py, capture_loaded_orange.py, live evidence and progress docs.
6. Добавленные тесты:12s isolatedDB live partial probe,188unit tests PASS.
7. Что остаётся неизвестным: physical quantity dialog/dragdrop, capacity display, relogUI, full optional metadata. Merge of compatible stacks not implemented.
8. Риски и альтернативы: native probe constructs requests programmatically, not physical interaction. Real sourceammo used rather than impossible multi-count weapon. MainDB unchanged.
9. Следующий самый полезный шаг: visible warehouse and quantity dialog, persistence after real relog, capacity/error feedback audit.

## 2026-09-12 — Warehouse relog and UI targeting

1. Что исследовано: fresh normal55s client launch against saved partial-transfer DB; computer-use skill/@oai/sky target enumeration.
2. Что доказано: relog sends warehouse7+2/inventory1 with same IDs, clientapplies6A; exit0/noFridaerrors. Two native window enumerations found no TI target.
3. Новые packet mappings: none.
4. Новые структуры: none.
5. Изменённые файлы: relog evidence/summary and progress docs.
6. Добавленные тесты: real fresh-session persistence readback; previous188unit status unchanged, no code edits.
7. Что остаётся неизвестным: cause of absent targetable window, physical warehouse UI, capacity display, optional metadata.
8. Риски и альтернативы: successful protocol/model callback is not visual proof; no UI input attempted. Running handle8339 polled to terminal exit0 before summary.
9. Следующий самый полезный шаг: target-window diagnosis and capacity/error presentation, then complete warehouse acceptance audit.

## 2026-09-12 — Warehouse rejection feedback

1. Что исследовано: generic shop_error_reply used for warehouse failures; client TGameSettings RTTI9dc2c2/warehouse_slots9dc46d.
2. Что доказано: warehouse failures previously displayed unrelated shop wording; dedicated mapping now emits warehouse/transfer reasons on verifiedF0/394 path.
3. Новые packet mappings: none; reused original localized394 command and its wait-clear behavior.
4. Новые структуры: warehouse_error_reply with capacity/quantity/equipped/ownership/selection and safe fallback messages.
5. Изменённые файлы: warehouse_service.py, loopback_exchange.py, test_warehouse_errors.py and progress docs.
6. Добавленные тесты: F0/394 argument shape, cp1251 reason text and no internal error leakage;189unit PASS.
7. Что остаётся неизвестным: TGameSettings capacity population, displayed maximum, physical UI and full optional metadata.
8. Риски и альтернативы: protocol feedback verified by encoding, newly localized messages not separately observed visually. Capacity source clue is not an implemented synchronization.
9. Следующий самый полезный шаг: trace TGameSettings.warehouse_slots population and warehouse display to align100-slot local server policy.

## 2026-09-12 — Warehouse capacity alignment
- Что исследовано: TGameSettings initialization and private warehouse UI capacity selection.
- Что доказано: original9dc891 writes3000;9b3677 reads u16+0x0e; kind0 selects widget3 and the same capacity.
- Новые mappings: settings globalad27a4, pointerac6008; warehouse_slots offset0x0e.
- Новые структуры: none.
- Файлы: config/city_catalogs.json default3000; tools/verify_warehouse_capacity_native.py; evidence/warehouse_capacity_native.json.
- Тесты: original instruction blocks PASS for3000 and17, configured default matches;189unit tests PASS.
- Неизвестное: rendered warehouse UI and physical transfers; optional marker/gift metadata.
- Риски: already running user client/server retains old100 policy until restart; no forced restart. Computer-use cannot enumerate TI window despite live process and ping replies. No screenshot claim; evidence seal deferred while live session runs.
- Следующий шаг: verify physical UI and complete item metadata support.

## 2026-09-12 — Restored game window control
- Исследовано: Delphi TApplication0x0 owner and visible TForm1.
- Доказано: adding WS_EX_APPWINDOW to TForm1 makes sky.list_windows return it; screenshot and click/select ProbeNew succeed.
- Mappings: actual hwnd5375458; exstyle0x10100 ->0x50100; owner unchanged.
- Структуры: no protocol change.
- Файлы: tools/window_compat.py, tools/capture_loaded_orange.py, evidence/window_target_diagnosis.json.
- Проверки: live adapter, enumeration, screenshot and selection; Python compile PASS.
- Неизвестное: fresh-launch integration not rerun; warehouse UI transfers remain to verify.
- Риски: adds application window/taskbar identity; no executable-on-disk change or restart.
- Следующий шаг: native warehouse UI verification.

## 2026-09-12 — Physical warehouse transfer and equipped deposit fix
- Исследовано: native UI equipment context menu and warehouse double-click.
- Доказано: direct equipped deposit sends6B kind0 actor1/first array, no separate unequip; prior server rejected it.
- Mappings: full equipped deposit clears placement atomically; response30 resets primary to300.
- Структуры: unchanged.
- Файлы: tio/warehouse.py; tests/test_warehouse_store.py; evidence/warehouse_equipped_ui.json.
- Тесты:191PASS; physical deposit icon and withdrawal empty warehouse verified; original callback1item1001 equipped0/slot0.
- Неизвестное: backpack item invisibility despite receipt; partial stack dialog and remaining metadata.
- Риски: main Beretta1001 now in backpack, not yet re-equipped; livePID16132 remains open. No missing or duplicated persisted item.
- Следующий шаг: fix backpack rendering to complete usable withdrawal/equipment cycle.

## 2026-09-12 — Backpack display recheck
- Исследовано: actual rendered backpack and repeated physical transfer/equip cycle.
- Доказано:1001 icon visible BEFORE changes; full repeat shows icon on warehouse, backpack and equipment in sequence. Earlier persistent invisibility diagnosis withdrawn; exact earlier observation delay cause unproven.
- Mappings: unchanged.
- Структуры: unchanged.
- Файлы: evidence/warehouse_equipped_ui.json, NEXT_TASK.md.
- Проверки: physical menu deposit, double-click withdrawal and equip; read-only DB confirms1001 equippedpet1,1002 equippedpet3,emptywarehouse.
- Неизвестное: partial-stack UI and remaining optional metadata.
- Риски: no code patch needed; avoid treating immediate pre-response screenshots as proof of render failure.
- Следующий шаг: partial-stack dialog and relog UI verification.

## 2026-09-12 — Source-backed shop assortment
- Исследовано: original base/items.cfg143 records, XML loader and native shop filters.
- Доказано:92 eligible ordinary-shop offers displayed; head/body/legs filters show native icons and source defense; ammo source pack quantities visible.
- Mappings: shop offer unknown_u32_02 now source packamount; CFG p_def -> for/add stat=pdef; armor itype9. Native filter requires weaponType1, pdef nonzero and matching bodypart. for/set rejected by readback, final for/add verified.
- Структуры: protocol unchanged; purchase supports all configured templates and source stack sizes. Stable offer1 Beretta/offer2 Knife preserved.
- Файлы: tools/build_item_fixture.py, config/city_catalogs.json, tio/shop.py, tests/test_city_catalogs.py, tests/test_shop.py, evidence/items_diagnostic.xml, provenance files, shop_expanded_ui.json.
- Тесты:192 unit PASS; live original client renders general list and three armor filters; metadata210/211/212 defense60/24/30 verified read-only.
- Неизвестное: historical prices/Reservation availability, complete semantics of all legacy fields and item-use/equipment behavior.
- Риски: all offers use provisional100credits per pack, not historical prices; stack resale still unsupported. Original source files unchanged.
- Следующий шаг: user paused warehouse; shop expansion delivered. Game left open PID14088/session91627 without automatic timeout. Further item behavior/pricing follows user priority.

## 2026-09-12 — Hiring and warehouse models
- Исследовано: market empty because both old candidates already hired; mobs.udf confirms humans1/2 and dogs3/4/5. Legacy body meshes referenced by CFG are absent from installed models.
- Доказано: native UI lists5offers, shows human/dog previews, completes two purchases, replenishes market; warehouse shows selected human/dog3D models. Relog callback returns both saved purchases.
- Mappings: nonhuman PetInfo schema for dog resources; candidate generations stride1000 independent per account. Default six human body IDs mapped to existing chr_man/chr_woman meshes/textures in generated XML only.
- Структуры: wire layouts unchanged; HireStore selects proper schema and human flag, validates current offer under BEGIN IMMEDIATE with wallet/roster writes.
- Файлы: tio/hiring.py, tio/city_catalogs.py, config/city_catalogs.json, tools/build_item_fixture.py, hiring/catalog tests, regenerated XML/provenance, evidence/hiring_models_ui.json.
- Тесты:193PASS; UI purchases Doberman pet4 and male pet5; wallet9700->9500, gold10000; native relog5actors HP100/100.
- Неизвестное: historical hire prices/stats, full dog battle/equipment semantics, remaining old item mesh mappings.
- Риски:100credits and stats are local placeholders; portraits remain silhouettes. Two test purchases intentionally retained in main roster and charged200credits.
- Следующий шаг: follow user priority. Game remains open PID15088/session73069 unlimited; warehouse model and hiring request completed.

## 2026-09-12 — Ability recovery started
- Исследовано: ability.cfg, skills.xml loader, skill packet dispatcher/readers.
- Доказано:74legacy records,27nonzero IDs; active/passive and dog abilities have explicit per-level parameters with gaps. Runtime requires skills.xml.
- Mappings:80->8c1bd8 learned list;8E->8c2624 learning list;AA->8c2174 tree. Exact fixed reader widths preserved in codecs; unknown32 not claimed price.
- Структуры: AbilityCatalog preserves complete source fields, absent levels/parameters remain unknown; AbilityEntry codecs reject profile mismatch/truncation.
- Файлы: tio/abilities.py, tio/protocol/abilities.py, tools/build_ability_catalog.py, config/abilities.json, tests/test_abilities.py, tests/test_ability_protocol.py, evidence/abilities_recovery.json and reader disassembly.
- Тесты:198unit PASS. Live ability use not tested; no claim of playable abilities.
- Неизвестное: complete skills.xml semantics, actor eligibility, learning requests/requirements/prices, missing level parameters.
- Риски: legacy CFG does not establish modern effects; do not grant skills or apply stats from names alone.
- Следующий шаг: continue native skills.xml loader verification, server learning/persistence and combat/UI integration. User ability objective remains unfinished.

## 2026-09-12 — Native skills.xml catalog
- Исследовано: original Perks_XMLLoad9d61xx and legacy ability.cfg per-level definitions.
- Доказано: original client loads17abilities/62levels from generated skills.xml via existing B9 shared-config delivery. Native table exact IDs, levels, values, active flags and mapped AP/range/cooldown verified read-only.
- Mappings: table text -> numeric value; Active -> OP_ACTIVE; AP -> apConsume; Range -> castRange; explicit uniform targets and other known XML fields preserved. Record stride0x348, AP offset0x327.
- Структуры: only complete explicit level/value groups exported;10incomplete definitions excluded. Missing/nonuniform fields recorded in provenance, not inferred from first level.
- Файлы: tools/build_skills_fixture.py, tools/verify_skills_live.py, tools/loopback_exchange.py, tools/probe_item_fixture.py, tests/test_skills_fixture.py, evidence/skills_diagnostic.xml, skills_provenance.json, skills_native_readback.json, abilities_recovery.json.
- Тесты:200unit PASS; original running client62records PASS. AP8 for Dog Deathbite and AP7 for Dog Cure verified. Existing client skills.xml protected from replacement; temporary generated file cleanup only for matching content.
- Неизвестное: learning requests/eligibility/prices, incomplete source levels, passive effects and complete combat semantics. Catalog loading does not establish playable abilities.
- Риски: native defaults for omitted parameters are not recovered balance. No skill grants or combat activation, original source assets and player DB unchanged this stage.
- Следующий шаг: recover learning and persistence, then native human/dog ability UI and combat effects. Game left open PID2988/session47303, unlimited, data/skills-xml-live.log.

## 2026-09-12 — Ability requests and persistent state
- Исследовано: learning UI callers8ad4b0/8b10c0, my_perks caller8b1228 and native writers8c2420/8c245c.8E tail copied into metadata+0x310; price/resource meaning not established.
- Доказано:8F and90 carry actor32,ability32 only; no level or price supplied by client. Six original writer executions match Python encoding.
- Mappings:8F invoked from other_perks and tree selection;90 invoked from my_perks, reset/refund policy remains unknown. Added strict request codecs rejecting truncation/trailing bytes.
- Структуры: ability_states stores account,actor,revision,learned80 packet. Trusted server CAS replacement validates owned actor, explicit catalog level, duplicate IDs and retains opaque wire fields.
- Файлы: tio/protocol/abilities.py, tio/ability_state.py, tools/verify_ability_requests_native.py, tests/test_ability_protocol.py, tests/test_ability_state.py and request/UI evidence.
- Тесты:204unit PASS;6native writer cases PASS. Persistence/reopen, account isolation, stale snapshot rejection and injected database failure rollback tested. Native probe isolates only transport acquisition/flush, original integer writers execute.
- Неизвестное: eligibility, resource denomination/costs, reset semantics and post-learning native UI. No live learning roundtrip performed.
- Риски: snapshot API is server-internal, not an authorization policy; do not wire raw client data to it. No ability grants, resource spending, passive stat changes or mainDB mutations this stage.
- Следующий шаг: confirm requirements/cost and response behavior, connect authoritative learning transaction and human/dog UI. Full learning remains unfinished.

## 2026-09-12 — Learning integration and Russian effect text
- Исследовано: confirmation m183/m184, AA tree reader8c2174, C812 writer62fa90, Delphi short-string conversion40c06c->40b1ec/globalac7900.
- Доказано: learning/forgetting prices denominated in credits. Native AA field reads and C812 writes pass. Human skill tree rendered and user purchased four first ranks. Cyrillic corruption caused by runtime ACP1252; CP1251 and tree refresh restore effect text.
- Mappings: C812->learned80; A9->treeAA;8F learning transaction->80+AA+assets. AA id/rank/learned/requiredlevel/learnprice/forgetprice.90 forgetting not enabled.
- Структуры: explicit local100credits/rank, species whitelist and sequential ranks limited by actor level; quote revision prevents stale purchases; wallet and learned state commit atomically. No passive stat/combat implementation.
- Файлы: config/ability_learning.json, tio/ability_learning.py, protocol/abilities.py, tools/loopback_exchange.py, tools/capture_loaded_orange.py, tests/test_ability_learning.py, tools/verify_skill_tree_native.py and evidence/ability_learning_ui.json.
- Тесты:208PASS; nativeAA/C812 verification PASS;21human tree descriptions read back without question marks. Live screenshot shows effect +5 health in Russian.
- Неизвестное: original prices/eligibility, dog physical learning UI, relog verification, passive effects and combat; launcher codepage hook added but fresh launch not rerun.
- Риски: process-only codepage correction, Windows settings/original DLL unchanged. User purchases retained: pet1 skills1/2/4/6 level1, revision4, wallet9100/gold10000. Description of effect is not proof effect is applied.
- Следующий шаг: dog learning and relog checks, then passive/combat effects; forgetting remains disabled. Live session14066 left open.

## 2026-09-12 — Derived passive maximum health
- Исследовано: PetInfo native direct stores8c4a12/8c4abc and ability1/16 source rank values.
- Доказано: maxHP field8c4a07->6008, currentHP8c4ab1->6006; native human/dog probes receive105maximum/73current independently.
- Mappings: human1 and dog16 add explicit rank value to baseline maximum. Current HP retained; no healing upon learning.
- Структуры: stored pet_packet remains baseline; projected roster reads join learned state in one read transaction. Learning sends derived66 after successful atomic wallet/state write; overflow rolls back whole purchase.
- Файлы: tio/passive_stats.py, tio/owned_pets.py, tio/ability_learning.py, tests/test_passive_stats.py, tools/trace_pet_info_native.py and passive_health evidence.
- Тесты:211PASS;2native health cases PASS; main saved pet1 read-only projection100->105/current100. Repeated reads, rank replacement, account isolation and overflow rollback covered.
- Неизвестное: remaining passive stat fields, full combat integration and live relog health display.
- Риски: no live process restart this stage; open game still runs earlier server. Stored baseline must never be overwritten with a derived snapshot. No mainDB mutation.
- Следующий шаг: live relog verification and carry/critical/defense/accuracy field recovery; health alone completed at server/codec layer.

## 2026-09-12 — Carry capacity passive
- Исследовано: actor RTTI and PetInfo writer destinations; adjacent counters identified by original localized UI labels.
- Доказано: RTTIa80e42 identifies6024 as max_weight;8c4b57 u16 reader stores it. Native probe380 verified.
- Mappings: human ability2 source value adds carry capacity, composing with health projection. Neighbor fields60c4..60d4 are kills/deaths/damage/rating.
- Структуры: same baseline projection; learning2 emits projected66; no derived values persisted over baseline.
- Файлы: passive_stats.py, ability_learning.py, trace_pet_info_native.py, test_passive_stats.py, passive_carry_native.json, actor_stat_rtti.json.
- Тесты:212PASS; native carry field PASS; repeated reads and simultaneous health/carry tested.
- Неизвестное: live carry bar and movement penalties, defense/accuracy/critical effects and active combat skills.
- Риски: live server still earlier version; no game restart or player DB mutation this turn.
- Следующий шаг: map ArmorClass6010 and baseAccuracy602c, verify live health/carry, continue full ability objective.

## 2026-09-12 — Human and dog defense passives
- Исследовано: ArmorClass native6010 and PetInfo8c4ac5; source p15d explicitly states additional dog armor. Accuracy602c consumer uses progression thresholds, not established attack percentage.
- Доказано: human and dog original readers accept115/152 armor in native field. Derived defense composes with existing health/carry and remains separate from stored baseline.
- Mappings: ability6/15 adds explicit source rank value to8c4ac5; learning emits derived66. Do not use602c directly for accuracy bonuses without further evidence.
- Структуры: unchanged; overflow rejects before transaction commit; current health unaffected.
- Файлы: passive_stats.py, ability_learning.py, trace_pet_info_native.py, test_passive_stats.py, evidence/passive_defense_native.json.
- Тесты:213PASS, two native armor cases PASS and repeated read/account-specific projections.
- Неизвестное: battle damage reduction formula, accuracy and critical modifiers, live relog stats and full active skill use.
- Риски: packet projection is not proof of combat damage reduction. Live game not restarted; player baseline unchanged.
- Следующий шаг: recover accuracy/critical combat consumers, live verify projected city stats and continue active abilities.

## 2026-09-12 — Active cast and authoritative healing
- Исследовано: original cast writer8c0730 and UI callers8b5550/8b5cc9; shared movement/turn state and Dog Cure source records.
- Доказано:81 carries abilityID,actorID,unknown32,cell x/y; own-target caller uses actor cell. Three original integer writer executions match codec.
- Mappings: Dog Cure23 level1 explicit heal12/AP7/CD3; higher ranks lack explicit cooldown and are rejected by preparation instead of silently inheriting.
- Структуры: BattleActor optional health/maxhealth; prepared trusted healing rules; atomic HP/AP/cooldown update; owner-turn counter shared with AP refill and cleared on removal. ArenaService validates active owner/deadline/selection.
- Файлы: protocol/ability_cast.py, battle_state.py, arena_service.py, verify_ability_cast_native.py, test_ability_cast.py, test_battle_healing.py and ability_cast_native.json.
- Тесты:218PASS; native cast3cases PASS. Healing caps, AP shared with movement, invalid casts preserve state, cooldown reuse, removal cleanup, missing learned/rank data and foreign/expired turns covered.
- Неизвестное: native health/cooldown reply path, animation/effect updates, missing higher-rank cooldowns and original turn counting semantics.
- Риски: no live cast routing or combat roster initialization yet. Cooldown policy explicitly local N following actor turns. MainDB/game unchanged.
- Следующий шаг: recover native health/status response, initialize battle abilities from saved roster and verify live Dog Cure roundtrip; broader skill objective remains active.

## 2026-09-12 — Healing HP/AP and ability cooldown replies
- Исследовано: original4E serializer/status4 and7F/01 serializer62f038 with8c0790 receiver; native skill button state consumers.
- Доказано: HP writes actor6006. Skill status3/4 updates rank31e,state338,remaining328; state3 draws cooldown fraction, state4 passes button activation gate before AP check. Native serializer/model cases pass.
- Mappings:4E actor/count1/status4/newHP/effect0;7F01 actor/count32/(skill32,rank8,state32,remaining32). Native list consumer uses byte counter, so encoder rejects over255 entries.
- Структуры: healing replies HP/AP/cooldown fully serialized before state mutation; own-turn snapshots sent before38; preparation retains trusted rank. Local cooldown3->2->1->0 becomes available state4.
- Файлы: protocol/health.py, protocol/ability_status.py, battle_state.py, arena_service.py, verify_health_native.py, verify_ability_status_native.py, related tests and evidence JSON.
- Тесты:220PASS; original health3cases and ability status3cases PASS. Service full cooldown/reuse cycle, packet order, invalid requests and serialization failure preserve atomic state.
- Неизвестное: original dispatcher/rendered UI roundtrip, animation callbacks, trusted battle roster initialization, historical turn-count policy and higher-rank missing cooldowns.
- Риски: no live81 route yet; native probes stub lookups and stop before UI. User DB and running game unchanged. This is not proof of playable arena healing.
- Следующий шаг: initialize diagnostic dog actor from saved learned skills, route81 to validated service replies, verify live health/AP and cooldown before broader active effects.

## 2026-09-12 — Saved dog battle roster and healing transport
- Исследовано: existing3B dog equipment branch, city66 dog slots and scene bootstrap.
- Доказано: native3B reader consumes complete generated packets for resources3/4/5, preserves HP100/max100 and IDs. Dog slots map16/4/1024 via543f/546e/549d, matching66 pet47f5/4821/484d.
- Mappings: dog scene and human scene use explicit resource profile; learned80 follows3B before scene-end41 (live sequence still unverified).
- Структуры: one SQLite read transaction loads owned actor, inventory and learned ranks; projects passives without replacing baseline; initializes health and trusted healing rule before battle mutation. No missing-rank cooldown inheritance.
- Файлы: tools/battle_actor_fixture.py, battle_roster_fixture.py, loopback_exchange.py, trace_battle_soldier_native.py, verify_dog_battle_native.py, tests/test_battle_roster_fixture.py, evidence/dog_battle_native.json.
- Тесты:221PASS; native dog reader3cases PASS; transport py_compile PASS. Saved wounded dog73->85/AP33, reopening baseline73, account isolation, no learned skill, missing rank cooldown verified. Initial test cleanup failed from unclosed SQLite test connection, fixed with closing context and rerun passed.
- Неизвестное: live dispatcher7F01, UI/model scene lifecycle with learned80, animation and full arena gameplay.
- Риски: running gamePID20936 observed but unchanged; new81 route is implemented but not live verified. Local40AP/spawn2,2/empty8x8 remain diagnostic. Character/account relationship remains existing loopback synthetic login policy.
- Следующий шаг: controlled separateDB live dog cast probe and native cooldown/HP/AP readback, then rendered UI verification. Full ability objective remains active.

## 2026-09-13 — Arena selection prerequisite requested by user
- Исследовано: mercenary selector original callbacks, state5ff1, request67 and current live window.
- Доказано: original8c3c94 serializes67 actor32/action32 gatedac5dec; four native cases PASS. Predicate93f6ac checksstate4; RTTI explicitly names Unfitable_Soldier, so4 must NOT be treated as available reserve.
- Mappings:67 action carried from DL, zero in known unfit-removal callbacks93f6d5/93fa59/93fe4d; exact add/slot action not yet established.
- Структуры: raw strict pet-state request codec only; no speculative saved-state mutation or live route.
- Файлы: protocol/pet_state.py, verify_pet_state_native.py, test_pet_state.py, evidence/pet_state_native.json; data/arena-selection-observed.log.
- Тесты:222PASS;4native sender and5predicate cases PASS. PhysicalUI opened quick equipment; greenarrow click produced no tracked67 callback. Live all5owned actors have state1, list remains empty.
- Неизвестное: available-list filter/slot status transitions and add/remove protocol; lobby join/wait and server bot remain incomplete.
- Риски: no state migration made; live user session8244 remains open. Attempted launcher rejected due existing catalog (existing process untouched). Earlier tentative reserve interpretation rejected by RTTI evidence.
- Следующий шаг: recover selector add/list predicates and actual selected squad; restore normal create/wait/start with server AI before any further live healing probe. Full ability goal remains active with this prerequisite.

## 2026-09-13 — Survival immediate search prerequisite
- Исследовано: user-corrected flow and physical selector after relaunch; category global and candidate original callbacks.
- Доказано: UI restores selected human/dog/human and available humans. Clicking Survival goes directly to Loading, no create dialog. Current category0 read live.94389c/94cc84 is equipment action, not mode switch.
- Mappings: existing BA03 writer remains known category/count, but exact physical Survival request and acknowledgement not yet confirmed; no speculative wire route added.
- Структуры: immutable queue tickets selected IDs/levels from trusted roster; idempotent enqueue; player preference; local5s bot fallback proposal; cancel/stale protection; consume after scene preparation.
- Файлы: tio/matchmaking.py, tests/test_matchmaking.py, evidence/survival_queue_progress.json.
- Тесты:225PASS, includes duplicate/cancel/botdeadline, failed-preparation retention, eligible real match priority and stale consumption.
- Неизвестное: native search acknowledgement, bot spawn/actions, cancellation packet and full live battle lifecycle.
- Риски: queue not wired, fallback proposal is not an implemented AI opponent. Current game remains Loading in session46677; no player balance/skill edits.
- Следующий шаг: capture physical request/response handshake, connect immediate search and bot scene, then implement opponent actions before ability tests.

## 2026-09-13 — Выживание: вход в очередь и отмена, live UI
1. Исследовано: физический выбор режима и сохранённый loopback; BA0B/BA08 original consumers.
2. Доказано: Выживание отправляет BA030003; BA0B снимает Loading; own ready1 показывает ожидание без дополнительной готовности; BA05 отменяет и возвращает selector.
3. Mappings: BA03 category0/count selected; BA07 readiness; BA08 room32/char32/flag8 changes member110 only for matching IDs. BA0B shared soldierInfo level/NPC/avatar/rank offsets; rank wire minus1.
4. Структуры: SurvivalService wraps immutable SurvivalQueue tickets; transient search IDs, roster snapshot, pause/resume; no combat room created.
5. Файлы: tio/survival_service.py, tools/loopback_exchange.py, tests/test_survival_service.py, tools/verify_arena_ready_native.py.
6. Тесты: 227 unittest PASS; original BA0B 3 cases and BA08 4 cases PASS. Physical waiting shows 3 humans/dog silhouettes and automatic ready, cancel returns selection.
7. Неизвестное: two BA0B pet integers, exact member level convention, original balance. AI and scene launch remain unimplemented.
8. Риски: local zero avatar/rank defaults; final readiness toggle only native/unit verified. Main wallet and selected squad unchanged; client left running.
9. Следующий шаг: prepare full squad and bot scene, validate fresh trusted roster before commit, consume match proposal only after success, wire automatic loading/turns.

## 2026-09-13 — Автоматическая тренировочная сцена
1. Исследовано: полный отряд, повторная проверка сохранённых данных, автоматический переход и бот.
2. Доказано: physical Arena -> Survival -> wait5s -> scene -> first turn;37bot снимает Synchronization. По первому live журналу после timeout отправлены bot3D/AP и новый human38.
3. Mappings: actor3B existing ID/owner/x/y параметризованы, серверные стороны player/bot;37 отправляется для обоих участников.
4. Структуры: PreparedSurvival, transient mirrored opponent, ArenaService.start_survival, deterministic movement policy.
5. Файлы: tools/survival_scene.py,tools/battle_actor_fixture.py,tio/arena_service.py,tio/training_bot.py,tools/loopback_exchange.py,tests/test_survival_scene.py.
6. Тесты:228PASS; mixed human/dog full squad packet positions, snapshot DB unchanged, stale selection rejection, room loaded gating and bot/human turn cycle. Live singleton scene/turn and sync fix confirmed.
7. Неизвестное: foreign bot model invisible despite participant entry; actual scene visibility/identity gate unresolved. Terrain remains small diagnostic ground.
8. Риски: no attacks/damage/victory, bot movement visual not verified, room25 soldier groups empty, gameplay not complete. Main wallet8700/gold10000 at initial observation unchanged.
9. Следующий шаг: fix foreign actor rendering, verify full squad scene and bot movement physically, then attacks and completion; keep healing test paused.

## 2026-09-13 — Загрузка карты32x32
1. Исследовано: ground.xml, maps/*.s, native717e1c named entry reader ->6cd690(name,x,y), existing scene grid mapping.
2. Доказано: новый35 -> renderer generates textured32x32 map, first turn and route preview; client log485tiles/12render targets.
3. Mappings: config dimensions and spawn coordinates drive both35 and3B/BattleField. Named entry2bytes are x/y passed DL/CL.
4. Структуры: ArenaMap validates bounds, distinct unblocked spawns, supportedground0..4, safe fragment paths and reserved rectangles.
5. Файлы: config/arena_map.json,tio/arena_map.py,tools/survival_scene.py,tests/test_arena_map.py.
6. Тесты:230PASS including invalid dimensions/ground/traversal/spawn collision; live textured map confirmed.
7. Неизвестное: exact .s object loading/render mapping, original arena layout, secondlayer obstacle codes.
8. Риски: local open layout; initial4tree trial not visibly confirmed, removed from final config to prevent invisible blocked cells. Current session remains initialtrial; future matches load final config.
9. Следующий шаг: native .s loader/dependencies, cover/buildings and collision verified together.

## 2026-09-13 — Здания и укрытия на карте
1. Исследовано:6cd8bc suffix .s,6d24d0 TI SET loader,32byte header/grid/72byte model rows.
2. Доказано: extensionless ground entry loads assets; physical UI shed/fence/two box groups; log4sets and modelpaths.
3. Mappings:header width12,height14,count16; two-byte rowmajor cells; names in72byte rows.
4. Структуры: imported hashes/footprints/models, ArenaMap bounds and blocked cells2/3. Cover-class distinction not restored.
5. Файлы: tools/import_arena_fragments.py,config/arena_fragments.json,config/arena_map.json,tio/arena_map.py,tests/test_arena_map.py.
6. Тесты:231PASS incl source box2x2 blocking, no AP or partial position on rejected path, free perimeter. Live visible buildings and client resource load confirmed.
7. Неизвестное: LOS/projectile cover classes, object damage/destruction, original arena placements.
8. Риски: local conservative blocking of classes2/3, unset0 correction requires next launcher; source originals untouched.
9. Следующий шаг: verify physical movement around cover, bot visibility then attacks/LOS.


## 2026-09-13 — Индивидуальный обзор и видимость противников
- Исследовано: mobs.udf, ability.cfg, tutorial tut_1000.xml, Sight/getSight/setSight RTTI и обработчики 3B/66, чтение HUD.
- Доказано: оригинальные 3B8c567f и66 8c4a1b читают байт и передают setSight(a86df8); HUD9b521d получает getSight(a86de4). Обучение говорит о девяти клетках. Значение9 людям установлено по прямому запросу пользователя.
- Mappings: 3B8c567f = sight, 66 8c4a1b = sight; соответствие добавлено в battle_actor_fixture.
- Структуры: BattleActor.sight_radius; VisibilityView хранит видимый набор и отправляет43/3B при изменениях. Каждый живой наблюдатель использует свой радиус; боты не преследуют скрытых целей.
- Файлы: tio/battle_state.py, tio/visibility.py, tio/training_bot.py, tools/survival_scene.py, tools/loopback_exchange.py, tools/battle_actor_fixture.py, tools/verify_sight_native.py, tests/test_visibility.py, tests/test_survival_scene.py, evidence/sight_native.json.
- Тесты: 234 unittest PASS; original-hash sight verifier PASS. Проверены включённая граница9, исключение10 и точки вне круга, обзор собаки12, смерть наблюдателя и согласованность пакета с сервером.
- Неизвестное: исходные значения обзора собак; default_sight/max_sight требуют дальнейшего исследования.12 для собак остаётся временным.
- Риски: геометрия LOS и непрозрачность blocked являются локальной политикой; нет затемнения поверхности карты. Модель противника ещё не подтверждена визуально. Eye9 на финальном коде ещё не проверен в живом окне.
- Следующий шаг: запустить обновлённый launcher, проверить eye9 и скрытие/появление врага; продолжить поиск исходных параметров собак. При последней проверке процесс ti отсутствовал.


## 2026-09-13 — Обход укрытий тренировочным противником
- Исследовано: training_bot, ArenaService.move, текущие ограничения обзора, оригинальные TANetBattleAttacked RTTI и delayed callbacks.
- Доказано: прежний жадный алгоритм запрещал первый шаг от цели и застревал у U-образных препятствий. Новые маршруты используют BFS и проверку движения сервера.
- Mappings: новых пакетов не включено; найдены TANetBattleAttacked621502 и delayed963606 для дальнейшего восстановления атаки.
- Структуры: approach_path возвращает кратчайший кардинальный маршрут к доступной клетке рядом с одной из видимых целей; скрытая занятость не используется при планировании.
- Файлы: tio/training_bot.py, tests/test_training_bot.py, tests/test_survival_scene.py, NEXT_TASK.md, WORK_REPORT.md.
- Тесты:237PASS; U-обход с первоначальным удалением от цели, выбор доступного врага вместо запертого, расход AP и атомарный отказ при скрытом препятствии. Интеграция Survival сохраняет видимость и отсутствие изменений БД.
- Неизвестное: оригинальная дальность оружия, формат полного обмена атакой и причина невидимой модели противника.
- Риски: подход вплотную — локальное поведение, пока без стрельбы/урона. Обработка движения поклеточная; живая анимация длинного пути в этом шаге не проверена.
- Следующий шаг: восстановить формат запроса атаки и ответа с анимацией, проверить видимую модель противника в живом клиенте. Полный бой и победа ещё не реализованы.


## Оружие и патроны — 2026-09-13
Исследовано: оригинальный base/items.cfg и строки reload/recharge/actionPoints/ammo в silver.dll. Доказано:39 записей оружия,12 типов ammo,23 явные связи ammo_id (количество связей проверяется по каталогу). Новые сетевые mappings не добавлены. Структуры:WeaponStats, WeaponCatalog, BattleActor.weapons. Файлы:config/weapon_catalog.json, tio/weapons.py, tools/import_weapon_catalog.py, tools/survival_scene.py, tio/battle_state.py, tests/test_weapons.py, tests/test_survival_scene.py, evidence/weapon_catalog.md. Тесты:239PASS; совместимость патронов, исходные значения Beretta, запрет висячей ссылки ammo, отсутствие выдуманной цены reload, загрузка оружия в Survival. Неизвестное:AP reload, распределение rnd_dam, XML binding damage/ammo и финальный баланс. Риски:нет исполнения атаки/расхода патронов; отсутствие ammo_id не означает бесконечные патроны. Следующий шаг:восстановить native XML stat binding и механику перезарядки.


## 2026-09-13 — Первый серверный выстрел и граната
Исследовано: native49/4B, XML consume/attackType, сетевые материалы по перезарядке. Доказано: оригинальные writers5casesPASS и consume stores3casesPASS. Mappings:49 actor/x/y;4B typed attack result, схема в tio/protocol/battle_attack.py. Структуры:Combat, AttackRequest/Result/Hit, инвентари на бой и CAS-персистентность. Файлы:combat.py, protocol/battle_attack.py, arena_service.py, weapons.py, equipment.py, survival_scene.py, loopback_exchange.py, normalize_weapon_xml.py, build_item_fixture.py, items_diagnostic.xml, verify_attack_native.py, verify_weapon_consume_native.py, tests/test_combat.py, tests/test_equipment.py. Тесты:248PASS плюс native writers/consume. Неизвестно:результат флагов0 в живой анимации, исходный reload AP, полная формула урона/броня. Риски:локальные вероятность попадания, base+uniformrnd и радиус взрыва; нет брони/критов/разброса, победы и стрельбы бота; невидимая модель врага не решена. Следующий шаг:живой тест на отдельной БД, подтвердить анимацию/HP/AP/счётчик патронов, затем защита и завершение боя. Основная БД тестовыми предметами не изменялась.


## 2026-09-13 — Укус собаки
Исследовано: оригинальная дистанция a8907c, текущая память клиента PID24536 и запросы на скриншоте. Доказано:собакаid4 имеет primary333/min1/max1/AP5; скриншот лечения отправляет81/23. Дистанция боя округляется до целого; диагональ соседней клетки равна1. Изменено:combat_distance.py, combat.py, weapons.py, tests/test_combat.py, verify_combat_distance_native.py. Укус использует333 независимо от экипировки собаки, не требует патронов;5AP,50+случайные10 по старомуCFG. Проверки:соседние и диагональные цели, дальность2 и угол стены, отсутствие расхода инвентаря. Живое окно было в городе; анимация укуса не проверялась. Исходная формула урона/броня остаётся отдельным этапом. Следующий шаг:перезапуск сервера и проверка обычного клика собакой по соседнему противнику.


## 2026-09-13 — Инвентарь при загрузке боя
Исследовано: prepare_survival, Combat и обработчик2F. Причина: полные инвентари были зарегистрированы на сервере, но отсутствовали в пакетах загрузки сцены. Изменено: отправка собственных30 после3B до41; запрос2F возвращает текущее боевое состояние только выбранных собственных бойцов. Файлы: tools/survival_scene.py, tio/arena_service.py, tools/loopback_exchange.py, tests/test_survival_scene.py, tests/test_combat.py. Проверки: покупка100 патронов и2 гранат через ShopStore в временной БД, точное сохранение предметов в пакетах сцены, порядок загрузки, отсутствие утечки инвентаря ботов, остаток после выстрела.250 тестов PASS, py_compile PASS. Ограничение: визуальная проверка клиента не выполнена; обновление требует перезапуска сервера и нового боя. Основная БД не изменялась. Следующий шаг: подтвердить список предметов и расход патронов в живом бою.


## 2026-09-13 - Battle weapon switch and grenade throw
Investigated: screenshot33/49, city equipment routing, Combat snapshot and CAS. Fixed: battle equipment now changes authoritative inventory and persisted state together; original option4 selects primary mask16. Validates active turn, own selected living human and owned weapon. Shares CAS persistence with attack; updates future visibility snapshots. Files: combat.py, arena_service.py, loopback_exchange.py, test_combat.py. Validation:251 unit tests PASS and py_compile; gun-to-grenade switch then throw consumes one grenade and7AP, preserves bullets and persists remaining inventory; foreign turn and stale write rejected. User confirms live dog bite animation/damage. Live grenade animation and remaining inventory display not yet verified. Switch AP remains unchanged provisional policy. Next: new battle after restart and live grenade verification.


## 2026-09-14 - Medical items, secondary weapon and AP
Evidence: original base/items.cfg lines1244-1281 supplies medical9/10/11 healing10/30/50 and AP1/3/5. Client screenshot identifies6D actor32 and swap tooltip1AP. Original8b72c8 writer verified3cases using real scalar serializers; transport flush/UI isolated. Implemented self-treatment33/FF, inventory CAS, HP cap and atomic refusal; city/battle secondary slot128 and6D swap costing1AP; humans15AP per turn as explicit user configuration (original value not established). Files: combat.py, arena_service.py, equipment.py, loopback_exchange.py, survival_scene.py, verify_weapon_swap_native.py, tests/test_combat.py, tests/test_equipment.py, tests/test_survival_scene.py.254 tests PASS, native3PASS. Live medical and swap UI still require restart/new battle. User verified grenade animation/area damage and dog bite. HP persistence after battle and original base humanAP remain open.


## 2026-09-14 - Dog movement and current/maximum AP
Read-only client snapshot: dogHP1 at12,16, remaining living enemy13,14, dead units13,16 and13,18. Range2 correctly rejects bite. Fixed server collision and bot route occupancy to ignore dead actors; regression moves wounded dog through corpse then bites for5AP while live enemy cell remains blocked. Dog turn budget17, human15 as requested. Recovered HUD maximum:9b5078 reads actor6028;3B byte8c5694 -> store8c569c; RTTI max_action_points. Visibility snapshot sends turn budget as maximum instead of default0, preserving it after spending AP.255 tests PASS, compile PASS. Existing live session was not modified/restarted. Next: restart/new battle to verify17/17,15/15 and corpse traversal in game.


## 2026-09-14 - Battle victory/defeat and reward
Recovered original4C summary reader95e4d0, dispatcher962521, outcome0/1/2 and results-window call719460; native numeric-reader3cases PASS. Ordinary six counters and soldier XP not recovered; left zero. Manual indexed victory criterion: eliminate opponent units; assault rating formula not reused for credits. Local fallback reward1000 winner,0loss/draw. Arena stops terminal turn and settles/release room; SQLite UUID/account ledger prevents duplicate credit and checks overflow. Tests cover victory/defeat/draw, lethal attack, repeated/conflicting settlement, retry and new match. Live result window/city transition still unverified; no server restart. Full result statistics, health progression and match crash recovery remain future work.


## 2026-09-14 - Finish button return to Reservation
User screenshots confirm4C victory UI; prematureF0/24/117 mixes city and battle and shows exclusion text. Removed premature transition. Completed match acknowledgement2A01 now sends originalF0/449 close-results/event13 branch, current town3 and open117, followed by saved city roster/inventory. Native dispatcher and branch verified with managed event/UI calls isolated;258 unit tests PASS and compile PASS. Repeat acknowledgement cannot reward again, new match clears acknowledgement. Live teardown still unverified; requires restart/new battle.


## Result statistics
Mapped4C summary fields via718263 UI and russian.lng st04/st05/st06/st07/st10/st15: kills/losses/dealt/received/credits/tax. Owner counters now accumulated after committed combat attacks, clamped to actual HP removed; healing does not subtract prior damage. Friendly damage excludes offensive credit but includes received damage and losses. Reward display uses1000 on victory matching settlement. Native reader verifies nonzero fields in3 outcomes. City return confirmed by user. Live revised summary not yet verified.


## 2026-09-14: post-battle treatment and roster refresh

Local policy: 2 credits per missing HP, including defeated humans/dogs. Native result callback719f60 calls7196fc (Finish) before optional8c3d84. The latter sends7C,u8count,u32 IDs for own injured actors. Native8c8ad4 sums own missing HP (flag41);8c8b30 multiplies by float referenced throughac5ac0. verify_treatment_native executes original sum/multiply/round: missing303HP ->606credits, opposing actor excluded.

Compatibility limitation: full arena-settings packet is not recovered. Existing instrumented launcher sets the native tariff float on719460 entry, using the same Python CREDITS_PER_HP constant as server. This modifies runtime parameter memory only, not DLL files, and preserves original checkbox rendering/request generation. Requires restarting run_reservation.py/client to load new handler.

Battle reward transaction now also persists final HP for persistent own actors; reserves and inventory/maxHP baseline are retained. Treatment7C accepted only after completed battle, outside rooms; validates IDs, charges and restores HP atomically using projected passive maxHP. Unknown actors/insufficient funds roll back; repeated healthy requests cost0. No checkbox means wounds remain. Finish still exits on2A01; if treatment fails, city displays error and wounds remain.

Roster: immediate66/30 after449 can precede asynchronous scene teardown. Added saved full roster66/30 refresh on post-battle4Affffffff and50 panel requests, disabled in an active room and cleared for a new survival match. Includes reserves/dogs; inventory requests2F do not trigger recursive refresh. Visual confirmation of this timing fix still needed in restarted client.

Validation:265 unit tests pass, original treatment price, finish449 branch and4C reader pass. Recovery tests cover charge retry, insufficient funds, rollback of reward plus wounds, humans/dogs with passive maxHP, roster refresh gating. No live server/client restart performed.


## Armor equipment (2026-09-14)
City action33 now accepts client-derived head2/chest4/legs8 armor rules in addition to weapons16/128. Source: evidence/items_diagnostic.xml (same catalog delivered to client), bodypart/dogs_only/level_required. Heavy Battle 242/243/244 and SE251/252/253; dog255 level2,265/266 level5 chest4. FF chooses template slot and toggles; explicit target replaces prior same-slot equipment atomically. Species and level checks occur inside transaction; human weapons blocked for dogs. Reject default body meshes65500+, freak-only and unsupported complexarmor. Preserve IDs/counts/opaque fields and inventory persistence.
Battle actor builder already maps equipped30 slots to3B: human2/4/8; dog4 ->8c546e. Tests verify full Heavy Battle set, SE replacement/removal, three dog armors, model fields in scene serialization, level/species/slot rejection. No new armor damage-absorption formula implemented: this change restores equipment and its model templates. Native visual rendering still requires live check after restart. User confirmed previous roster-return fix.


## Armor mitigation (2026-09-14)
Implemented local physical damage policy in tio/armor.py and Combat.attack: floor(raw*100/(100+sum equipped p_def)), minimum1 for positive raw. Armor p_def/bodypart/dogs_only loaded from same client-derived items_diagnostic.xml as game. Only compatible equipped head2/chest4/legs8 count; backpack, incorrect slots/species, body meshes and unsupported complex/freak armor excluded. Example Heavy Battle Armor243:85 defense;50raw->27HP,23absorbed. Dog Solid266:160;50->19HP,31absorbed. Not claimed as original server formula.
Applies to bullets, melee/dog bites and frag317 including friendly splash, independently per victim.4B absorbed_damage carries mitigation; statistics track actual HP removed after mitigation and HP clamp. Inventory CAS still precedes HP/stat commit. No armor wear, hit locations, penetration or passive-defense additions implemented in this step.
Validation:274 unit tests PASS including bullet packet absorbed field, bite, dog armor, grenade friendly fire, missed shots, overkill, removal/backpack/species rejection. No live client restart; next live battle required for visual confirmation.

## Helmet slot and armor visuals correction
User confirms chest/legs equip but helmet33 option00 rejected. Correct native requested head mask is1 (option0), not2. Updated equipment and mitigation rules;3B builder already maps mask1->8c525b. Tests verify Heavy Battle Helmet SE251 in head1 and p_def63 mitigation.
Legacy armor CFG assets (armor_battle_heavy_se_torso/arms/hands, battle_se.jpg etc.) are absent from installed client. Added tools/normalize_armor_models.py integrated into build_item_fixture.py. Modern man_armor_*/woman_armor_* single-piece meshes replace all legacy parts; textures armor_battle/armor_battlese/armor_combat/etc. are verified on disk. Female binding uses native w_model_N (a70ceb) and w_texture_N (a70dbf). All three dog armor meshes and textures already exist and are retained. Generic208 Helmet and222 Leather Jacket lack original models: explicit local fallback combat_light_head and military_light_chest. Legacy226 bodypart chest contradicted legs mesh, normalized to legs. Complex tank/FEA assets normalized too, but their equip rules remain unsupported. Freak armor untouched (not user human/dog scope).
Generated catalog/provenance rebuilt from original items.cfg without editing client originals.277 tests and original target conversion25cases PASS. Tests verify all supported armor meshes/textures exist, female variants, removed obsolete multipart fields, helmet native option0->slot1->battle template and defense. No live renderer verification: restart launcher/client and visually check male/female/dog armor. Earlier claim head2 in old notes is superseded by screenshot-derived head1 correction.

## Shop loading investigation 2026-09-14
> SHOP CHECK 2026-09-14: User confirms shop works after fresh launch. 92 offers delivered by 73/74, original reader returned and helmet/ammo lists visually populated. Warehouse-to-shop spinner not reproduced; no catalog/equipment rollback or claimed root-cause fix. Added read-only tools/trace_shop_live.py. 277 unit tests, native request6 and catalog reader4 PASS. Diagnostic runs use data/shop-regression.sqlite3, not main DB. See evidence/shop_loading_investigation.md.
Root cause remains unresolved; recovery after relaunch and user confirmation are verified. No functional shop change was made.

## Warehouse to shop waiting fix
> SHOP FIX: Reproduced live waiting=1/shop_loading=1; original991940 drops73 while waiting. Added launcher shop_request_retry.js to defer and resend once after original wait reset. Unknown/empty city2F now returns F0/394 instead of silence (unknown30 cannot reset waiting). Controlled original-client probe PASS: deferred1/resumed1/real74reply1/wait0/loading0. 278tests, native request9 and F0 reset PASS. Restart launcher/server to apply. See evidence/shop_loading_investigation.md and shop_retry_live.json.
The precise predecessor of the initial stale wait remains untraced. Lost shop-request behavior and recovery through real74 are proven. Catalog/armor/balance/saved purchases unchanged by the fix.

## Female Exo Armor equipment
> FEMALE ARMOR: Female Exo Armor263 and SE264 now equip on resource2 women through33 option2/chest4 or FF toggle. woman_only enforced; men/dogs rejected atomically. Local full-suit occupancy chest+legs: removes separate torso/trousers, reverse equip removes suit, helmet/weapons preserved. Battle3B chest template and p_def208 included. Existing woman_armor_fea/fease assets retained. 280tests PASS, compile PASS. Live renderer/equip not checked this turn; restart launcher/server. Other complex armor still unsupported.

## Weapon damage XML binding
> WEAPON DAMAGE DISPLAY 2026-09-15: All39 source weapons now emit for/set patk=p_dam and for/add patk=rnd_dam(default0). Original native stores132/134 and interval readera7a4de verified39cases; 281unit tests PASS. Colt M4 raw40-55. normalize_weapon_xml integrated builder already, existing XML updated without rebuilding shop/prices. Server balance unchanged; full live tooltip not verified, requires client restart. See evidence/weapon_damage_display.md and weapon_damage_native.json.
Power/PowerMin/PowerMax are not used as substitutes for weapon patk. DamageFade remains default100 to match current server no-falloff policy; accuracy and other balance untouched. No live process restarted or saved inventory modified.


## SC shop 2026-09-19
> SC SHOP 2026-09-19: B404/05 catalog, B407/08 cart, B409 add, B40A decrement, B406 direct purchase and B40B Gold checkout implemented; B40C gets empty original B40D auxiliary list. User authorized provisional Gold assortment: config/sc_catalog.json has 35 source-defined templates, local25/100Gold, enhancement0, stock1000/account. Atomic wallet/inventory/stock/cart persistence; warehouse-aware IDs, no main-account test grants. 297 unit tests PASS, 11 original-x86 cases PASS (numeric readers/writers + catalog consumer, UI isolated). Visual mouse-driven purchase remains for user testing. See SC_SHOP.md.


Sources: original silver.dll readers655368/655bd0, consumer8eba9c, cart8eb8d0, requests656204/6560bc/655e68/655e94/65601c/655f2c, TItem/TSCItem RTTI. Config seed derives client templates and packamount but does not claim historical SC offers/prices. Implemented Gold-only purchase and persistent cart; no item effect/enhancement combat changes. Native verification exposed and corrected cart count width (u32). Main launcher started for user UI testing; no programmatic purchases in main database.


## SC icon compatibility 2026-09-19
> SC ICONS 2026-09-19: User confirms SC purchases persist; screenshots/log identify eight absent legacy icons (318 Smoke Grenade,319 Molotov,321 Land Mine,223/224 Rags,236/237/238 Raider). tools/normalize_item_icons.py replaces only those references with installed substitute assets, integrated into build_item_fixture.py. Existing shared XML patched without rebuilding shop/prices; audit confirms exactly eight image-only edits and zero missing image references. Evidence sc_icon_replacements.json; source client files and saved items unchanged. Visual replacement confirmation requires client restart; artwork is substitute, not recovered original.


## Item enhancement 2026-09-19
> ENHANCEMENT 2026-09-19: Ordinary Upgrade Kit30 via native C8/2A now atomic/persistent. User accepted +25 if client confirmed: default metadata store A712FD verified. Manual p83 provides safe+1/+2, later63%, +65 durability, SE failure->+0 initial durability. Chances are server parameters, not hardcoded original probabilities. config/enhancement.json; runtime client settings compatibility hook (full settings packet still unrecovered). Both effective and saved item levels update; damage/armor bonuses follow current x86, differing from old manual; battle modifiers integrated. 305 unit tests PASS (8 new), native request/item/stat/max/chance probes PASS. Main-account inventory untouched by automated attempts. Existing running launcher needs restart; manual live upgrade window test pending. See ENHANCEMENT.md.


## Upgrade Kit visibility
> UPGRADE KIT VISIBILITY 2026-09-19: User screenshots show physical kit30 in shop but hidden in mercenary backpack on warehouse page. Saved kits intact. Native HideUpgradeBoxes panel+2A2 intentionally excludes template30 in six render/layout/mouse branches. tools/upgrade_kit_inventory.js clears it on city inventory creation and immediately for existing AC4BD4 squad panel (created before ORANGE hooks). Standard launcher includes adapter; DLL and DB unchanged. 36 native branch cases +2 property stores +original kit targeting mode PASS. Live readback confirmed kit type13/usable1, AC567C->AC4DB0; panel hide1->0. Original kit -> target -> C8/2A path retained. Client launched, current owned process patched; manual user visual/action check pending. See ENHANCEMENT.md and evidence/upgrade_kit_inventory_live.json.


## Personal warehouse Upgrade Kit filter
> PERSONAL WAREHOUSE KITS 2026-09-19: User confirmed live SE +2 guaranteed, +3 success then failure resets+0; M60 +2 then failure destroys it. Separate personal-warehouse filter still hid template30 after deposit (four kits present in DB). tools/upgrade_kit_warehouse.js removes only XOR EBX,EBX at9159F7 and9171B2 in CheckItemForFilters/ResortOutputList; checks both byte pairs before process-memory patch. Other filters and IsSimpleUpgradeKit unchanged. Wired into launcher; applied live to current client with readback, disk DLL unchanged. Native24 warehouse filter combinations pass (plus36 inventory),20 warehouse tests pass; isolated kit deposit/withdrawal/upgrade roundtrip passes. User should refresh personal warehouse list; visual confirmation pending.


## Rental shop
> RENTAL 2026-09-19: User confirms personal warehouse Upgrade Kits work. Implemented B40E/F catalog and B410 rentals, native original x86 verified for 300 offers, currencies and timed inventory flag. User chose provisional Gold-only prices in config/rental_catalog.json. Atomic leases persist UTC expiry, own warehouse preserves deadlines, login/city loop removes expired items, battle defers until completion. Existing sale/upgrade restrictions reject rentals. Manual p31 rental tax added to battle rewards/summary; equal-share fixed team reward and peak equipped counts are explicitly local policy. 313 unit tests PASS; native rental probe PASS. Main DB untouched by tests; currently running launcher needs restart. User live UI/purchase verification pending. See RENTAL.md.


## Enhancement level requirement research
> REQUIRED LEVEL RESEARCH 2026-09-19: User confirms rental basically works; asks why Heavy Battle Armor SE +10 requires4, +15 requires7, +20 none. Original A7C500/A7B480 exactly reproduce it: upgrade>=20 in effective OR real field bypasses extra gate and keeps base requirement. Source template252 has no level_required; XML loader default1. Native87 cases PASS, no gameplay changes. Admin 2012-04-28 announcement confirms existing20-25 stat trimming; old manual p14 describes battle caps. Current emulator DOES NOT trim effective upgrade by mercenary/battle bracket (rentals/enhancement write both fields equal). Separate missing server behavior identified, not an incorrect rental tooltip. See evidence/item_required_level_research.md and native JSON/probe.


## Effective equipment enhancement caps
> ENHANCEMENT SCALING 2026-09-19: User requested applying recovered balance rules. Implemented tio/enhancement_limits.py caps1-3:+3,4-6:+10,7-10:+15,11-15:+20,16+:+25. City high20+ wire projection preserves real upgrade; sub20 keeps original equip gate, now enforced server-side in city/combat. Combat keeps raw canonical inventories for CAS, calculates capped gun/armor bonuses, sends projected ItemLists; scene and Arena refresh use same projection, mirrored bots included. No DB migration; real levels/rental timers/durability preserved. 319 full tests PASS then7 focused tests PASS including additional scene integration (320 total now). Native8 effective/real pairs and18 arithmetic cases PASS. Per-mercenary caps only, not full cross-bracket TrueSkill. Restart emulator for live verification. See ENHANCEMENT_LIMITS.md.

## Stage 7 — 2026-10-08

Реализованы пять специальных предметов: Molotov 319, Land Mine 321, Grenade Launcher 323, Flamethrower 324 и Dynamite 325. Покупки, расход принадлежащих бойцу предметов, мины и горение входят в общий сохраняемый бой; переподключение и восстановление не повторяют взрыв или тик. Smoke 318, Flash 320, разминирование и поиск чужих мин пока не поддержаны. Цены, отсутствующий исходный урон мины, горение и топливо через прочность — явные правила эмулятора, а не восстановленный исторический баланс. Подробности и native/server-проверки: [special-items.md](reports/stage7/special-items.md), [special-items-tests.json](reports/stage7/special-items-tests.json).

Почта передаёт текст, кредиты и вещи персонажу, в том числе вне сети. Тариф: 100 кредитов за письмо + 5% передаваемых кредитов + 25 за каждое вложение; срок хранения — 10 дней. Дополнительные тарифы и лимиты являются политикой эмулятора. Нативный B70E/1 получает только деньги; вещи забираются через 6B/3 в инвентарь своего бойца. Глобальные ID почтовых вложений и новый ID остатка после частичного получения исключают повторное списание по старому запросу. Владение, количество, вместимость и допустимый вес проверяются до фиксации; квитанции и передача атомарны. ABI: [mail-abi.md](reports/stage7/mail-abi.md); datastore и настоящий TCP-обмен: [mail-native-store-validation.json](reports/stage7/mail-native-store-validation.json), [mail-transport-validation.json](reports/stage7/mail-transport-validation.json).

Один аккаунт поддерживает до пяти сохраняемых персонажей с отдельными кошельками, отрядами, предметами, XP, званиями и боями. Каждый новый персонаж получает заданные пользователем 3000 кредитов и 0 Gold; прежние сохранения не переинициализируются. Второй вход того же логина и смена персонажа для обхода незавершённого боя запрещены. Подробности и проверки создания/выбора/повторного входа: [characters.md](reports/stage7/characters.md), [characters-validation.json](reports/stage7/characters-validation.json).

Командный рейтинг учитывает обычный бой 2×2 четырёх разных логинов, уровни 4–20, без ботов. Состав пары сохраняется; оба результата фиксируются один раз в транзакции награды. Нужен вражеский урон обеих сторон; зачёт ограничен тремя встречами любой пары противоположных логинов за 24 часа. Сезон — календарный месяц UTC, незавершённый бой сохраняет исходный месяц, закрытый архив неизменяем. Формула пар, сезонность и ограничения — явная политика эмулятора; старый дуэльный рейтинг сохранён. Команды обычного чата: `!teamrating`, `!teamrating all`, `!teamrating YYYY-MM`, `!seasons`. Подробности и проверки четырёх аккаунтов: [team-seasons.md](reports/stage7/team-seasons.md), [team-seasons-validation.json](reports/stage7/team-seasons-validation.json).

Автоматические проверки используют изолированные данные, оригинальные native читатели/писатели и серверные обмены нескольких аккаунтов. Итоговый полный локальный прогон: 1404 проверки, 7 пропусков, без ошибок; все 36 runtime-файлов оставались неизменными ([отчёт](reports/stage7/local-validation-revision2.json)). Изолированная копия VPS: 162 проверки, 1 пропуск оригинального Windows DLL, без изменения рабочего кода или данных ([отчёт](reports/stage7/candidate-revision2/remote-validation.json)). Исходный DLL проверен локально: 21 почтовый и 10 специальных native случаев. Эти проверки не подтверждают отображение GUI.

Развёрнуто 2026-10-08 в 08:58 UTC на действующем multiplayer-хостинге: сохранены все 189 прежних аккаунтов, 186 кошельков и содержимое 82 существовавших таблиц; резервная копия БД и предыдущего кода — `/root/tio-before-stage7-y6b9dzn3`. Загружен только код, локальные данные игроков не переносились. [Развёртывание](reports/stage7/deployment.json), [заключительная проверка](reports/stage7/hosted-health-final.json): четыре порта работают, SQLite integrity OK, хэши всех 36 файлов совпадают, сайт/API не перезапускались, ошибок журнала и незавершённых боёв нет. Лаунчер 0.1.4 и его manifest не заменялись.

На живом сервере два обычных новых QA-аккаунта создали по два персонажа через native-протокол и 12 соединений со строгой проверкой TLS. Отправлены 10 кредитов офлайн-получателю с комиссией 101; повтор отправки/получения не удвоил перевод. Вторичные балансы 2889/3010 сохранились после входа, оба первых персонажа остались на 3000/0. Команды рейтинга и сезонов ответили; существующие сохранения и глобальные боевые результаты не изменились. [Hosted QA](reports/stage7/hosted-qa.json). После QA всего 191 аккаунт и 190 кошельков; все проверочные соединения закрыты. Боевые спецпредметы, получение вещей и рейтинг четырёх участников проверены автоматически на изолированных данных, а не в GUI на хостинге.

Ручная GUI-проверка после обновления:

- Два игровых клиента: купить спецпредметы, проверить установку/взрыв мины, горение и расход боеприпасов, затем переподключение в тот же бой.
- Отправить письмо с кредитами и вещами отключённому персонажу; получить деньги, частично забрать вещи и повторить запрос без дополнительной выдачи.
- Создать и выбрать второй персонаж; проверить 3000/0, покупку и повторный вход, затем неизменный кошелёк первого персонажа.
- Четыре разных аккаунта уровней 4–20: завершить бой 2×2 с уроном обеих сторон; проверить `!teamrating` и `!seasons` у всех участников после повторного входа.

