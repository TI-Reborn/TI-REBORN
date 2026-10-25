# Полный набор тестов вне CI — 25 октября 2026

CI (`tools/run_server_checks.py`) запускает выборку из ~680 тестов. Весь набор состоит
из 3101 теста в 395 модулях. В чистой облачной копии 25.10.2026 он давал 188 провалов
и 297 ошибок, и за этим шумом не было видно настоящих регрессий.

## Как запускать

```bash
python tools/run_full_tests.py --json full.json          # весь набор, ~20 минут
python tools/run_full_tests.py test_rental test_sc_shop  # отдельные модули
```

Каждый упавший тест попадает в одну из категорий:

- **environment** — нет входных данных, которых намеренно нет в репозитории:
  - `evidence/` (кроме трёх XML), `reports/`, `web/`, локальные папки `assets/`;
  - установленный клиент (`C:\Program Files (x86)\TIOnline`);
  - необязательные пакеты (`pefile`, `unicorn`, `waitress`, Blender и др.).

  Причина ищется и в исходном исключении (`raise … from`), и в тексте ошибки загрузчика модуля.
- **known** — перечислены в `tools/full_tests_known.json`, у каждого есть категория и пояснение.
  Если такой тест начинает проходить, раннер сообщает об этом (`known_now_passing`), чтобы список не устаревал.
- **real** — всё остальное. Код выхода 1 только при наличии real.

## Результат после очистки

| | Было | Стало |
| --- | --- | --- |
| Провалы + ошибки | 485 | 249 |
| из них environment | — | 115 |
| из них known | — | 90 (retired-gold 48, superseded-client-status 19, local-artifact 16, not-merged 7) |
| из них real | — | **44** |

### Обновлено под нынешние правила (без изменения игрового кода)

| Модуль | Что изменилось в правилах |
| --- | --- |
| `test_rental` | Аренда только за кредиты; аренды истекают партиями, потому что у склада города свой лимит. Было 99 провалов, остался 1 — вопрос к владельцу (ниже). |
| `test_sc_shop` | SC только за кредиты; новые номера лотов; огнестрел приходит с пачкой патронов; кредитные лоты без лимита склада. |
| `test_premium_account` | Премиум покупается за кредиты по цене из конфига. |
| `test_shop` | Огнестрел в обычном магазине приходит с патронами. |
| `test_shop_completion` | Магазин открыт в городах, на базах и у входа в шахты. |
| `test_achievements` | Номер SC-лота. |
| `test_alliance_service` | Сервер больше не отправляет отправителю его собственное сообщение (клиент показывает его сам). |
| `test_achievement_noncity_delivery` | У входа в шахту теперь есть склад, и награды выдаются там. |
| `test_appearance` | Таблицу онбординга теперь создают сами хранилища. |
| `test_outpost_equipment_copy` | В рейтинговый бой допускаются только бойцы с полным здоровьем. |
| `test_weapons`, `test_weapon_damage_xml`, `test_city_catalogs` | Новые снайперские винтовки и гранаты; нож продаётся за кредиты. |
| `test_armor_models`, `test_armor_missing_parts` | Пропускаются без установленного клиента. |
| `tools/import_weapon_catalog.py` | SVD строится из источника 312 только если он есть во входных данных. |
| `tools/benchmark_battle_checkpoints.py` | Часы фикстуры заморожены, поэтому шаг делается за пределы `END_TURN_REPEAT_SECONDS`. |

### Требует решения владельца

- **SVD (5013) нет в каталоге аренды.** Винтовка продаётся и улучшается, но не сдаётся в аренду. Это решение или упущение? Тест `test_rental.test_complete_equipment_catalog_and_all_filter_combinations` проверяет, что каталог аренды совпадает со списком предметов, допустимых к аренде.
- В репозитории нет кода, на который ссылаются тесты: `tio.performance.timed_block`, `tio.battle_recovery.treat_updates` (его добавил бы `tools/check_recovery_roster.py`), `MultiServer.initialize_character_economy`, `launcher/build_archive.py`, `launcher/build_menu_interface_update.py`, `web/`. Возможно, эти файлы есть только в локальной папке `C:\TIO-emulator`.

### Осталось real (44) — нужен разбор

Часть провалов — тяжёлые сетевые тесты (`test_battle_crash_recovery`, `test_multi_account`, `test_battle_failure_isolation`), которые падают по таймауту при общей нагрузке, а по одному обычно проходят. Остальное — вероятно, тоже устаревшие ожидания: вклады клана «только в городе», правила склада, состав пакетов оружия. Но среди них могут быть и настоящие регрессии, поэтому они оставлены видимыми.

| Модуль | Тест | Ошибка |
| --- | --- | --- |
| `test_battle_core` | `test_piercing_line_hits_allies_but_not_off_ray_or_behind_wall` | AssertionError: Items in the first set but not the second: |
| `test_battle_crash_recovery` | `test_two_tcp_accounts_resume_after_forced_server_process_exit` | TimeoutError: timed out |
| `test_battle_failure_isolation` | `test_unexpected_worker_failure_does_not_disconnect_other_tcp_account` | AssertionError: (<class 'EOFError'>, <class 'ConnectionResetError'>) not raised |
| `test_battle_item_effects` | `test_catalog_extension_ids_checked_against_installed_and_server_catalogs` | AssertionError: 11 != 12 |
| `test_battle_recovery` | `test_new_health_capacity_does_not_bank_idle_time` | AssertionError: Tuples differ: (b'f\x01\x00\x00\x00\x06\x00\x00\x00Shrek\x0[757 chars]00',) != (b'N\x01\x0 |
| `test_battle_recovery` | `test_session_passive_updates_and_city_treatment_without_finished_battle` | AssertionError: b'N\x01\x00\x00\x00\x01\x00\x00\x00\x04\x00\x00\x00c\x00\x00\x00\x00' not found in [b'f\x0 |
| `test_battle_screen_fixes` | `test_delayed_duplicate_cannot_finish_next_turn_or_reset_deadline` | AssertionError: 1 unexpectedly found in {1: (268435457, frozenset({1073741825}), 100.1)} |
| `test_battle_weapon_regressions` | `test_encrypted_attack_sends_full_item_metadata_after_skill_snapshot` | AssertionError: Lists differ: [75, 78, 48, 78, 78, 247, 249, 251, 59, 48, 78, 78] != [75, 78, 48, 78, 78,  |
| `test_clan_benefits` | `test_defense_fund_escrow_split_conserves_and_failure_is_atomic` | ClanRejected: Взносы доступны в городе |
| `test_clan_benefits` | `test_uncontested_defense_fund_refunds_owner_without_minting_tokens` | ClanRejected: Взносы доступны в городе |
| `test_clan_gameplay` | `test_private_fund_replay_and_leader_city_gates` | ClanRejected: Взносы доступны в городе |
| `test_clans` | `test_clan_chat_never_reaches_other_account` | AssertionError: 0 != 1 |
| `test_clans` | `test_protocol_lengths_and_wire_transfer` | AssertionError: Lists differ: [(1, 9950)] != [(1, 9950), (2, 10000)] |
| `test_clans` | `test_treasury_native_arrays_rights_and_conservation` | ClanRejected: Selected item is not in the owned source |
| `test_contract_world_namespace` | `test_duplicates_inside_private_namespace_remain_rejected` | AssertionError: ValueError not raised |
| `test_contract_world_namespace` | `test_private_shared_ids_allowed_without_changing_catalog_or_world` | AssertionError: Lists differ: [23, 24, 25] != [18, 19, 20] |
| `test_economy_runtime` | `test_offline_expiry_fenced_by_retained_owner_and_holder` | AttributeError: 'types.SimpleNamespace' object has no attribute 'config' |
| `test_forest_encounters` | `test_full_bag_award_merges_separate_auction_delivery_stacks_without_duplicates` | AssertionError: {65487: 2, 65488: 4} != {65487: 7, 65488: 4} |
| `test_forest_encounters` | `test_loot_shop_and_shared_player_auction_preserve_ownership` | WarehouseRejected: Склад доступен только в городе или у входа в шахту |
| `test_forest_encounters` | `test_victory_materials_once_and_shop_quantity_sale` | PurchaseRejected: Магазин доступен только в городе |
| `test_item_stacking` | `test_exchange_rollback_preserves_counts_and_sequence` | AssertionError: WarehouseRejected not raised |
| `test_item_stacking` | `test_login_compaction_is_local_idempotent_and_reserves_removed_ids` | AssertionError: {'inventories': 1, 'warehouse': False} != {'inventories': 1, 'warehouse': True} |
| `test_item_stacking` | `test_migration_rolls_back_all_locations_on_write_failure` | AssertionError: IntegrityError not raised |
| `test_item_stacking` | `test_wire_partial_transfer_merges_in_both_directions_even_when_full` | AssertionError: Lists differ: [(20, 40), (21, 12)] != [(20, 52)] |
| `test_miners` | `test_client_zone_bounds_match_server_and_keep_ids` | AssertionError: Lists differ: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21,  |
| `test_miners` | `test_live_session_routes_map_catalog_and_hire` | AssertionError: Lists differ: [98, 102, 78, 48, 78, 78, 200, 98] != [98, 102, 48, 78, 78, 200, 98] |
| `test_multi_account` | `test_new_accounts_create_retry_select_customize_and_relogin` | AssertionError: b'N' != b'f' |
| `test_multi_account` | `test_reversed_handoffs_same_ip_isolation_and_restart` | AssertionError: Missing reply f0 |
| `test_multi_account` | `test_wall_two_humans_six_bots_repeat_skip_and_timeout` | TimeoutError: timed out |
| `test_rating_completion` | `test_four_member_identity_retry_conflict_and_eight_auth_accounts` | ValueError: Unknown character owner identity |
| `test_rental` | `test_complete_equipment_catalog_and_all_filter_combinations` | AssertionError: Items in the second set but not the first: |
| `test_shared_battle_items` | `test_smoke_consumption_and_owner_turn_ttl_are_shared` | AssertionError: {1: {'kind': 'smoke', 'center': (8, 3), 'radius': 3, 'source': 1073741826, 'owner': 268435 |
| `test_shared_equipment_batch` | `test_preview_is_private_commit_and_retry_charge_two_once` | AssertionError: Lists differ: [48, 78] != [48] |
| `test_shooting_range` | `test_payment_limits_atomicity_and_all_four_modes` | AssertionError: b'\x01\x00\x01\x00' != b'\x01\x00\x01\x01' |
| `test_shooting_range` | `test_native_lobby_malformed_remote_and_repeat_requests` | AssertionError: b'\x01\x00\x01\x00' != b'\x01\x00\x01\x01' |
| `test_survival_scene` | `test_full_squad_bot_and_no_database_mutation` | ValueError: Dead actor cannot receive a turn |
| `test_team_ratings` | `test_character_rotation_cannot_reset_opposing_pair_limit` | ValueError: Unknown character owner identity |
| `test_team_ratings` | `test_same_authenticated_login_cannot_be_teammate_or_opponent` | ValueError: Unknown character owner identity |
| `test_warehouse_queries` | `test_encrypted_dispatch_routes_every_recovered_request` | AssertionError: False is not true |
| `test_warehouse_store` | `test_partial_withdraw_does_not_free_a_slot` | AssertionError: WarehouseRejected not raised |
| `test_warehouse_store` | `test_rejections_are_atomic` | AssertionError: WarehouseRejected not raised |
| `test_warehouse_store` | `test_snapshot_segments_and_read_only_store` | AssertionError: WarehouseRejected not raised |
| `test_weapon_skill_damage` | `test_every_original_weapon_selects_its_own_skill` | AssertionError: Items in the first set but not the second: |