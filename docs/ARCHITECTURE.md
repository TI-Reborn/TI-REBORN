# Архитектура

## Путь запроса

`python -m server` → `server/runtime.py` (конфигурация, preflight, завершение)
→ `server/multi.py` (multi-account, маршрутизация сессий)
→ `tools/loopback_exchange.py` (обмен пакетами и вызов сервисов)
→ `server/*` (координация участников) + `tio/*` (правила/хранилища)
→ `tio/protocol/*` (ответы клиенту).

`tools/loopback_exchange.py` — действующая runtime-зависимость, несмотря на историческое
название. Не переносить и не удалять её как «тестовую». Список обязательных сцен и
ресурсов определён в `server/runtime.py`: `RUNTIME_TOOLS`, `RUNTIME_ASSETS`.

## Карта задач

| Задача | Серверная координация | Правила / данные |
| --- | --- | --- |
| Вход, подключения, TLS | `runtime.py`, `multi.py`, `accounts.py`, `login_guard.py`, `tls.py` | `tio/protocol/transport.py`, `mode1.py`, `login.py` |
| Персонажи, отряд, экипировка | `avatar_service.py`, `public_profile.py` | `characters.py`, `owned_pets.py`, `squad.py`, `equipment.py`, `appearance.py` |
| Общий бой и переподключение | `team_arena.py`, `battle_reconnect.py`, `battle_journal.py`, `battle_events.py` | `combat.py`, `battle_state.py`, `battle_snapshot.py`, `battle_settlement.py`, `battle_rewards.py` |
| Арены и подбор | `ranked_arena.py`, `team_ranked.py`, `training_arena.py`, `wager_arena.py` | `matchmaking.py`, `team_lobbies.py`, `ranked.py`, `survival_service.py` |
| Боты и тактика | обработчики боя | `tactical_bot.py`, `training_bot.py`, `bot_finishing.py`, `mining_ai.py` |
| Мир, города, шахты, контракты | `world_runtime.py`, `city_services.py`, `mine_arena.py`, `contracts_service.py` | `locations.py`, `world_encounters.py`, `mining_service.py`, `pve_contracts.py`, `map_generation.py` |
| Магазины, банк, обмен | `bank_operations.py`, `bank_gameplay.py`, `market_operations.py`, `player_trade.py` | `wallets.py`, `bank_economy.py`, `shop.py`, `player_trade.py`, `player_auction.py` |
| Кланы, союзы, территории | `clan_service.py`, `alliance_service.py`, `territory_service.py` | `clans.py`, `alliances.py`, `territories.py`, `clan_benefits.py` |
| Почта, социальные функции | `mail_service.py`, `presence.py`, `social_commands.py` | `mail.py`, `social_completion.py` |
| Рейтинги и достижения | `ratings_public.py`, `public_profile.py` | `rating_visibility.py`, `rating_seasons.py`, `achievements.py`, `player_statistics.py` |
| HTTP-интеграции | `city_http.py`, `bank_gateway.py`, `web_status.py` | `game_operations.py`, `city_operations.py`, `registration/game_bridge.py` |

Имена в среднем столбце относятся к `server/`, справа — к `tio/`, если явно не указан путь.
Проверяйте фактических вызывающих через поиск: таблица показывает точки входа, а не весь граф.

## Хранение состояния

Путь SQLite вычисляет `ServerConfig.database`: `<data_directory>/reservation.sqlite3`.
Схемы и миграции распределены по хранилищам `tio/` и сервисам `server/`.
Единого миграционного каталога нет. Ищите `CREATE TABLE`, `ALTER TABLE`, `BEGIN IMMEDIATE`.
Общие операции должны сохранять атомарность денег/предметов и изоляцию аккаунтов.
Учитывайте повторные пакеты, reconnect, одновременные запросы и восстановление боя.

Каталоги `config/*.json`, XML и runtime-файлы `evidence/` связаны с бинарными кодеками и
клиентскими идентификаторами. Переименование и изменение ID требуют проверки протокола.
`config/server.toml` — безопасный исторический режим для preflight, а не production-конфиг.

Для отдельного мира Project Reborn можно задать `survival_duels = true` в секции
верхнего уровня `server.toml` при `multi_account = true`. Общая очередь режима 0
тогда собирает дуэль двух людей с одинаковым числом бойцов (1–3), в одном
уровневом диапазоне и пуле городов. Каждый сохраняет весь выбранный отряд.
По умолчанию действует групповая политика «Выживания» этого сервера.

## Границы передачи

Исходники лаунчера 0.1.42 включены в `launcher/`: .NET 10,
Windows Forms, `launcher/TioLauncher.csproj`. Нативный интерфейс контрактов
связан с `deploy/client_contracts_windows.py` и встроенным JSON-планом лаунчера.
Next.js-сайт, Unity и проприетарные EXE/DLL клиента не включены. Их интеграции
видны через HTTP-сервисы, документы и тесты, но сборку сайта/игрового клиента
нельзя воспроизвести только этим checkout.
`tools/` содержит и полезные offline-проверки, и сценарии, меняющие хостинг/клиент.
Не запускайте незнакомый скрипт по одному имени; сначала прочитайте его и `--help` там,
где CLI не выполняет действия при импорте. `verify_hosted_*`, `deploy_*`, `publish_*`
не являются обычными локальными тестами.
