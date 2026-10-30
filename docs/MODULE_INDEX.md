# Индекс Python-модулей

Автоматически извлечённые первые строки docstring; это описание автора модуля, а не отдельная проверка поведения.

## server/

| Файл | Назначение из docstring |
| --- | --- |
| [server/__init__.py](../server/__init__.py) | Standalone deployment of the existing single-account TIO server. |
| [server/__main__.py](../server/__main__.py) | См. код и вызывающие модули. |
| [server/accounts.py](../server/accounts.py) | Local account administration. No registration UI or REST service. |
| [server/alliance_service.py](../server/alliance_service.py) | Native alliance delivery from authenticated, shared SQLite clan authority. |
| [server/assault_arena.py](../server/assault_arena.py) | Native Assault4 groups and a journaled, exclusively real-account field. |
| [server/assault_public.py](../server/assault_public.py) | Read-only player views of accepted shared assault rewards. |
| [server/auth_errors.py](../server/auth_errors.py) | Expected, safe login refusals; storage and programming errors stay separate. |
| [server/avatar_service.py](../server/avatar_service.py) | Native avatar window; owner identity comes exclusively from the session. |
| [server/bank_gameplay.py](../server/bank_gameplay.py) | Private city !bank commands over shared authoritative bank SQL helpers. |
| [server/bank_gateway.py](../server/bank_gateway.py) | Loopback-only portal bank adapter; Stripe secrets never leave this process. |
| [server/bank_operations.py](../server/bank_operations.py) | Shared authoritative bank mutations; PINs never enter command snapshots. |
| [server/battle_events.py](../server/battle_events.py) | Project authoritative action events to each client, without teleport snapshots. |
| [server/battle_failures.py](../server/battle_failures.py) | Freeze a faulty shared match and finish its accounts without stopping peers. |
| [server/battle_journal.py](../server/battle_journal.py) | Checkpoint accepted gameplay with its economic writes before exposing replies. |
| [server/battle_reconnect.py](../server/battle_reconnect.py) | Bounded, account-bound reconnection to the existing authoritative PvP battle. |
| [server/city_http.py](../server/city_http.py) | Private bounded loopback HTTP owned by the live game router. |
| [server/city_operations.py](../server/city_operations.py) | Typed portal city operations inside the authoritative gameplay process. |
| [server/city_receipts.py](../server/city_receipts.py) | CityV1 account/request identity fence over original helper namespaces. |
| [server/city_services.py](../server/city_services.py) | Separate services V2 operations in the authoritative city process. |
| [server/clan_gameplay.py](../server/clan_gameplay.py) | Private owner commands and shared hourly clan benefits maintenance. |
| [server/clan_service.py](../server/clan_service.py) | Clan delivery uses each authenticated session's own Presence queue. |
| [server/config.py](../server/config.py) | Deployment settings; gameplay and wire formats remain in tio/. |
| [server/contracts_combat.py](../server/contracts_combat.py) | One journaled PvE field for a frozen party of real account owners. |
| [server/contracts_service.py](../server/contracts_service.py) | Opt-in cooperative contracts through private commands in native game chat. |
| [server/economy_runtime.py](../server/economy_runtime.py) | Shared city economy, offline timers and private inventory refreshes. |
| [server/failure_policy.py](../server/failure_policy.py) | Separate shared storage failure from an individual request/match failure. |
| [server/game_operations.py](../server/game_operations.py) | Transport-independent commands, checks and immutable operation results. |
| [server/login_guard.py](../server/login_guard.py) | Bounded token budgets before constructors and password hashing. |
| [server/mail_service.py](../server/mail_service.py) | Native character mail: quotes are inert, commits use durable escrow tokens. |
| [server/market_operations.py](../server/market_operations.py) | Shared mutations for barter, private shops and both auction systems. |
| [server/mine_arena.py](../server/mine_arena.py) | Shared, journaled underground instances entered by native checkpoint roles. |
| [server/mine_requests.py](../server/mine_requests.py) | Shared FIFO requests for native checkpoint defense and raid assistance. |
| [server/multi.py](../server/multi.py) | Concurrent sessions and shared authoritative matches on legacy wire fields. |
| [server/player_auction.py](../server/player_auction.py) | City-session adapter for the shared persistent player auction. |
| [server/player_trade.py](../server/player_trade.py) | Shared native barter; only each session's worker writes its game socket. |
| [server/presence.py](../server/presence.py) | Location membership shared by authenticated sessions; sockets remain thread-owned. |
| [server/private_market.py](../server/private_market.py) | City adapter for shared native private stores and persistent SC auction. |
| [server/public_profile.py](../server/public_profile.py) | Read-only public character projection. Never returns wallets or credentials. |
| [server/ranked_arena.py](../server/ranked_arena.py) | Native TrueSkill queue, one selected fighter per real account. |
| [server/ratings_public.py](../server/ratings_public.py) | Read-only squad standings inside the authoritative gameplay process. |
| [server/runtime.py](../server/runtime.py) | Host the existing exchange with a stable listener and orderly disconnect. |
| [server/service_operations.py](../server/service_operations.py) | Shared city-service commands for native and authenticated portal adapters. |
| [server/services_runtime.py](../server/services_runtime.py) | Native city services and delayed dismissal worker under the shared hub lock. |
| [server/services_v2.py](../server/services_v2.py) | Services V2 contract facade; deliberately separate from strict CITYV1 DTO. |
| [server/social_commands.py](../server/social_commands.py) | Private city chat adapter; backend provides the current authenticated actor. |
| [server/tactical_marks.py](../server/tactical_marks.py) | Authenticated B2/06 tactical marks, delivered to allies through B2/07. |
| [server/team_arena.py](../server/team_arena.py) | Shared team lobbies and one authoritative battlefield per paired teams. |
| [server/team_ranked.py](../server/team_ranked.py) | Fixed-pair team standings through ordinary native Team battle and chat. |
| [server/territory_service.py](../server/territory_service.py) | Project durable claims and UTC windows into the original TownInfo branch. |
| [server/tls.py](../server/tls.py) | Bounded TLS bootstrap and replaceable credentials for the shared backend. |
| [server/training_arena.py](../server/training_arena.py) | Noncapturable Assault4 training: native groups, eight real owners, three tours. |
| [server/tutorial_arena.py](../server/tutorial_arena.py) | Private introductory scenes on the real shared authoritative hub/journal. |
| [server/wager_arena.py](../server/wager_arena.py) | Native wager lobbies; the common arena owns battlefield and settlement. |
| [server/warehouse_capacity.py](../server/warehouse_capacity.py) | Opt-in warehouse captions; all counts and lists share a read-only snapshot. |
| [server/web_status.py](../server/web_status.py) | Publish only aggregate runtime state for the private website adapter. |
| [server/world_runtime.py](../server/world_runtime.py) | Shared admission snapshots and authenticated online prison heartbeats. |

## tio/

| Файл | Назначение из docstring |
| --- | --- |
| [tio/__init__.py](../tio/__init__.py) | Evidence-led Total Influence protocol implementation. |
| [tio/__main__.py](../tio/__main__.py) | Offline application packet inspection; does not assume wire framing. |
| [tio/abilities.py](../tio/abilities.py) | Source-backed legacy ability definitions; absent parameters stay unknown. |
| [tio/ability_learning.py](../tio/ability_learning.py) | Atomic learning with explicit price policies and derived passive stats. |
| [tio/ability_prices.py](../tio/ability_prices.py) | Growing perk learning price shared by humans, dogs and miners. |
| [tio/restored_abilities.py](../tio/restored_abilities.py) | Perks the client knows (locale, icons, readers) but the legacy CFG lacks. |
| [tio/ability_progression.py](../tio/ability_progression.py) | Authoritative native90 forgetting and native console skill decreases. |
| [tio/ability_state.py](../tio/ability_state.py) | Versioned server-owned learned-skill snapshots, not a learning policy. |
| [tio/achievement_benefits.py](../tio/achievement_benefits.py) | Read-only bonuses from earned immutable achievement reward snapshots. |
| [tio/achievements.py](../tio/achievements.py) | Account achievements: transactional counters, once-only awards and prize queue. |
| [tio/alliances.py](../tio/alliances.py) | Account-authorized clan alliances; manual pp20–21, additive SQLite authority. |
| [tio/appearance.py](../tio/appearance.py) | Native C2S92 customization; catalog and credit prices from the client XML. |
| [tio/arena_equipment.py](../tio/arena_equipment.py) | Authenticated client extension for staged battle equipment. |
| [tio/arena_gears.py](../tio/arena_gears.py) | Native arena catalogue of supported, purchasable combat gear. |
| [tio/arena_map.py](../tio/arena_map.py) | Validated battlefield layouts assembled from original client fragments. |
| [tio/arena_rooms.py](../tio/arena_rooms.py) | In-memory waiting-room lifecycle. Wire handlers are deliberately separate. |
| [tio/arena_roster.py](../tio/arena_roster.py) | Project supported local owned actors into room soldierInfo. |
| [tio/arena_service.py](../tio/arena_service.py) | Arena rooms, authenticated actions, turn scheduling and local battle settlement. |
| [tio/arena_surroundings.py](../tio/arena_surroundings.py) | Bind decorative city surroundings after authoritative map validation. |
| [tio/armor.py](../tio/armor.py) | Local physical mitigation; p_def values come from the delivered client XML. |
| [tio/armor_display.py](../tio/armor_display.py) | Absolute shield readout; never write equipment totals into base pet storage. |
| [tio/assault_battle.py](../tio/assault_battle.py) | Shared three-flag Assault4 score, advanced once per complete battle cycle. |
| [tio/assault_map.py](../tio/assault_map.py) | Original three-flag assault scenes with connected symmetric admission zones. |
| [tio/avatars.py](../tio/avatars.py) | Free portraits using the native AC catalog and durable FC assignment. |
| [tio/bank_economy.py](../tio/bank_economy.py) | Shared currency/securities, physical item marks and real-payment order ledger. |
| [tio/base_fund_completion.py](../tio/base_fund_completion.py) | Personal defender-fund contributions; callers own shared lock and SQLite TX. |
| [tio/battle_checkpoints.py](../tio/battle_checkpoints.py) | Atomic server snapshots and exclusive account bindings in the hosted SQLite. |
| [tio/battle_doors.py](../tio/battle_doors.py) | Persistent per-battle doors; one AP, original cost_moves_opendoor default. |
| [tio/battle_equipment.py](../tio/battle_equipment.py) | Restore owned instance metadata after the native template-only actor snapshot. |
| [tio/battle_exchange.py](../tio/battle_exchange.py) | Atomic exchange of loose items between adjacent living mercenaries of ONE owner. |
| [tio/battle_hazards.py](../tio/battle_hazards.py) | Shared saved mines and burns using native battle notifications. |
| [tio/battle_item_effects.py](../tio/battle_item_effects.py) | Authoritative item effects, staged inventory writes and battle-only timers. |
| [tio/battle_item_visuals.py](../tio/battle_item_visuals.py) | Project persistent smoke/light/recon cells for one real battle recipient. |
| [tio/battle_loot.py](../tio/battle_loot.py) | Battle-local crates. Random tables are explicit local balance, not server data. |
| [tio/battle_modes.py](../tio/battle_modes.py) | Classic arena formats (manual p14); player limits and training turn policy. |
| [tio/battle_recovery.py](../tio/battle_recovery.py) | Paid treatment and durable out-of-battle recovery; rates are local policy. |
| [tio/battle_rejection.py](../tio/battle_rejection.py) | Finish a refused native action queue without moving or charging an actor. |
| [tio/battle_rewards.py](../tio/battle_rewards.py) | Authoritative PvP rewards, persisted once per match/account. |
| [tio/battle_settlement.py](../tio/battle_settlement.py) | Durable final reports, replayed through the idempotent reward transaction. |
| [tio/battle_snapshot.py](../tio/battle_snapshot.py) | Versioned JSON graph of server state with a fixed class allowlist. |
| [tio/battle_state.py](../tio/battle_state.py) | Authoritative grid movement with explicitly supplied local movement costs. |
| [tio/bot_finishing.py](../tio/bot_finishing.py) | Read-only, bounded kill forecasts for currently visible arena opponents. |
| [tio/character_identity.py](../tio/character_identity.py) | Separate authenticated logins from durable character save owners. |
| [tio/characters.py](../tio/characters.py) | Five owned native character slots with independent durable save owners. |
| [tio/cities.py](../tio/cities.py) | City rules from manual pp11–16; map composition remains emulator policy. |
| [tio/city_catalogs.py](../tio/city_catalogs.py) | Explicit local catalog policy; wire unknowns remain named as unknowns. |
| [tio/city_inventory.py](../tio/city_inventory.py) | Answer city inventory lookups for owners that still exist. |
| [tio/clan_benefits.py](../tio/clan_benefits.py) | Manual clan benefits on shared SQLite authority; callers own the transaction. |
| [tio/clan_ratings.py](../tio/clan_ratings.py) | Read-only native clan/alliance standings by real, spendable influence. |
| [tio/clans.py](../tio/clans.py) | Account-bound clans. All decisions and shared-asset writes use SQLite authority. |
| [tio/combat.py](../tio/combat.py) | First combat rules on original49/4B packets and inventory30. |
| [tio/combat_completion.py](../tio/combat_completion.py) | Manual HP capacity injection on the existing authoritative native33 route. |
| [tio/combat_distance.py](../tio/combat_distance.py) | Native a8907c: round(sqrt(dx*dx+dy*dy)), not a strict circular boundary. |
| [tio/combat_rolls.py](../tio/combat_rolls.py) | Manual p57: independent accuracy per projectile, catalog damage per burst. |
| [tio/contest_maps.py](../tio/contest_maps.py) | Original whole TrueSkill contest scenes; spawn selection is server policy. |
| [tio/contract_scene.py](../tio/contract_scene.py) | Shared PvE scenes from real account selections and frozen contract policy. |
| [tio/control_points.py](../tio/control_points.py) | Authoritative flag capture and simultaneous score ticks. |
| [tio/credit_economy.py](../tio/credit_economy.py) | Single spendable currency; binary Gold slots remain zero for native ABI. |
| [tio/crystal_market.py](../tio/crystal_market.py) | Persistent crystals and fixed-point quotes; no floating-point money writes. |
| [tio/db_transaction.py](../tio/db_transaction.py) | Join server-owned gameplay writes to one SQLite transaction per action. |
| [tio/dog_abilities.py](../tio/dog_abilities.py) | Dog rules: manual eligibility, CFG effects, explicit compatibility defaults. |
| [tio/durability.py](../tio/durability.py) | Manual p56 wear; native ItemList current/max/calculated-max words. |
| [tio/encounter_loot.py](../tio/encounter_loot.py) | Tradeable encounter materials, awarded atomically with victory settlement. |
| [tio/enhancement.py](../tio/enhancement.py) | Atomic ordinary Upgrade Kit attempts. Research: ENHANCEMENT.md. |
| [tio/enhancement_limits.py](../tio/enhancement_limits.py) | Real upgrades persist; only effective equipment bonuses follow the owner's level. |
| [tio/equipment.py](../tio/equipment.py) | Atomic equipment snapshots with explicitly supplied template/slot rules. |
| [tio/equipment_batch.py](../tio/equipment_batch.py) | Authoritative staged equipment with one atomic confirmation per owner turn. |
| [tio/equipment_bonuses.py](../tio/equipment_bonuses.py) | Original equipment effects: manual pp66/72/74 and items.cfg effect values. |
| [tio/equipment_templates.py](../tio/equipment_templates.py) | Persistent C5 templates; owned-instance gear and counted supplies. |
| [tio/hiring.py](../tio/hiring.py) | Local candidate hiring with atomic wallet/roster updates. |
| [tio/inventory_capacity.py](../tio/inventory_capacity.py) | One carried-item limit, after stacking, with safe legacy bag reduction. |
| [tio/item_boosters.py](../tio/item_boosters.py) | Persistent saved-fighter boosters; native33 consumes owned instance once. |
| [tio/item_stacking.py](../tio/item_stacking.py) | User-selected stack policy; merge only identical, loose item instances. |
| [tio/level_progression.py](../tio/level_progression.py) | Original cumulative level thresholds; explicitly local damage-XP policy. |
| [tio/localization.py](../tio/localization.py) | Offline translations for built-in messages, selected per receiving session. |
| [tio/locations.py](../tio/locations.py) | Persistent world-map travel using original1B/1D/1E and native interpolation. |
| [tio/mail.py](../tio/mail.py) | Atomic offline character mail with credit/item escrow and durable receipts. |
| [tio/map_generation.py](../tio/map_generation.py) | Bounded procedural assembly of original client fragments. |
| [tio/market_inventory.py](../tio/market_inventory.py) | Shared-market transfers: native item metadata, account-local IDs, atomic money. |
| [tio/matchmaking.py](../tio/matchmaking.py) | Server-owned survival queue, without player-created rooms. |
| [tio/mine_claims.py](../tio/mine_claims.py) | Explicit checkpoint ownership, frozen battle claims and operator audit. |
| [tio/mine_map.py](../tio/mine_map.py) | Original mine scenery with randomized reachable deposits and mutants. |
| [tio/mine_radio.py](../tio/mine_radio.py) | Battle-only original Skill28 radio; the absent AP rule is explicit policy. |
| [tio/mine_rounds.py](../tio/mine_rounds.py) | Shared mining round scores, idempotent mission wins and next-round tax. |
| [tio/miner_abilities.py](../tio/miner_abilities.py) | Miner rules with an explicit manual/legacy-data reconciliation. |
| [tio/mining.py](../tio/mining.py) | Authoritative drill lifecycle. Combat supplies remain battle-local. |
| [tio/mining_ai.py](../tio/mining_ai.py) | Mine hunters with personal perception and journal-compatible memory. |
| [tio/mining_service.py](../tio/mining_service.py) | Original checkpoint menu requests, role selection, scene entry and quotes. |
| [tio/onboarding.py](../tio/onboarding.py) | Durable creation -> appearance -> character selection workflow. |
| [tio/owned_pets.py](../tio/owned_pets.py) | Persist validated owned-pet and inventory snapshots together. |
| [tio/party_travel.py](../tio/party_travel.py) | One durable route for a consenting party; coordinates never come from peers. |
| [tio/passive_stats.py](../tio/passive_stats.py) | Derived city PetInfo stats; stored pet packet remains the base snapshot. |
| [tio/player_auction.py](../tio/player_auction.py) | Persistent shared player-auction escrow. No client-supplied owner or prices. |
| [tio/player_statistics.py](../tio/player_statistics.py) | Persistent authoritative battle totals and per-soldier legacy rating. |
| [tio/player_trade.py](../tio/player_trade.py) | Atomic direct barter between selected soldiers of two different accounts. |
| [tio/premium.py](../tio/premium.py) | Original C8/3A subscription purchase, C8/39 status, account-bound benefits. |
| [tio/private_shops.py](../tio/private_shops.py) | Persistent private-market sales and funded purchase requests (manual pp30-31). |
| [tio/protocol/__init__.py](../tio/protocol/__init__.py) | Application payloads only; ORANGE wire framing is not established yet. |
| [tio/protocol/abilities.py](../tio/protocol/abilities.py) | Skill list layouts from silver.dll readers8c1bd8 and8c2624. |
| [tio/protocol/ability_cast.py](../tio/protocol/ability_cast.py) | 81 from original8c0730; callers8b5550/8b5cc9 establish field order. |
| [tio/protocol/ability_status.py](../tio/protocol/ability_status.py) | 7F/01 skill state, original serializer62f038 and consumer8c0790. |
| [tio/protocol/achievements.py](../tio/protocol/achievements.py) | B501 query, B502 list and B503 award; original readers 9637BC/963AC8. |
| [tio/protocol/action_points.py](../tio/protocol/action_points.py) | 4E TANetStatusUpdate attribute10 updates own actor action points. |
| [tio/protocol/alliances.py](../tio/protocol/alliances.py) | Alliance AF family confirmed against original Silver 6e107c..6e1cbc. |
| [tio/protocol/arena.py](../tio/protocol/arena.py) | Arena BA02 room records; unknown numeric fields retain native offsets. |
| [tio/protocol/assault.py](../tio/protocol/assault.py) | Assault4 room ABI, original Silver 63916c..63b690. |
| [tio/protocol/asset_count.py](../tio/protocol/asset_count.py) | S2C C8/39 RECV_AssetCount: reader65802c, consumer7d4c28. |
| [tio/protocol/auth2.py](../tio/protocol/auth2.py) | Application0C two raw CStrings; application0D status. SILVER87d608/87d8a4. |
| [tio/protocol/battle_attack.py](../tio/protocol/battle_attack.py) | 49 native95dfe8 request;4B native6543fc/653d24 response. |
| [tio/protocol/battle_door.py](../tio/protocol/battle_door.py) | Native ti.exe6DC54C request3E and6F5CFF state3F. |
| [tio/protocol/battle_exchange.py](../tio/protocol/battle_exchange.py) | Native mercenary exchange6E (silver98F478), distinct from ground transfer40. |
| [tio/protocol/battle_ground.py](../tio/protocol/battle_ground.py) | BattleGround35 layout from silver.dll95dd78; map value semantics unknown. |
| [tio/protocol/battle_item_status.py](../tio/protocol/battle_item_status.py) | Native4E attribute12 is absolute sight (8c7a8b -> a86df8). |
| [tio/protocol/battle_item_visuals.py](../tio/protocol/battle_item_visuals.py) | F7/v1: explicit emulator-only recipient-visible item cell snapshot. |
| [tio/protocol/battle_loaded.py](../tio/protocol/battle_loaded.py) | Loading acknowledgement36 and member notification37, verified native. |
| [tio/protocol/battle_loot.py](../tio/protocol/battle_loot.py) | Original46 open,47 container list and40 transfer (98F5CC). |
| [tio/protocol/battle_members.py](../tio/protocol/battle_members.py) | Full wire25 structure; semantic aliases recovered from original RTTI. |
| [tio/protocol/battle_mines.py](../tio/protocol/battle_mines.py) | Original native mine UI: C8/3D deployment and C8/3F acknowledgement. |
| [tio/protocol/battle_move.py](../tio/protocol/battle_move.py) | S2C3D BattleSoldierMove: actor ID and byte coordinate pairs. |
| [tio/protocol/battle_over.py](../tio/protocol/battle_over.py) | Recovered ordinary4C summary and per-soldier XP, silver95e4d0. |
| [tio/protocol/battle_position.py](../tio/protocol/battle_position.py) | Open battle container46; original writer95E114 (actor u32,x/y u8). |
| [tio/protocol/battle_remove.py](../tio/protocol/battle_remove.py) | S2C43: silver8c7edc dispatches to8c71e0, reads one actor u32. |
| [tio/protocol/battle_soldier.py](../tio/protocol/battle_soldier.py) | BattleSoldierAdd3B read layout (8c5044 through8c5aab). |
| [tio/protocol/battle_turn.py](../tio/protocol/battle_turn.py) | Original turn messages: TurnNow C8/17, YourTurn38, Finished39, EndTurn3A. |
| [tio/protocol/binary.py](../tio/protocol/binary.py) | Checked little-endian primitives confirmed in silver.dll 0x605d68/8c/b8. |
| [tio/protocol/character_create.py](../tio/protocol/character_create.py) | Original SILVER889cdc request and88a79c result. Success semantics unknown. |
| [tio/protocol/character_select.py](../tio/protocol/character_select.py) | Only the proven empty branch of SILVER889eac CharSelectInfo10. |
| [tio/protocol/chat.py](../tio/protocol/chat.py) | 21 send (9ff706), 22 receive (9fed8c); UTF-16LE terminated text. |
| [tio/protocol/city_catalogs.py](../tio/protocol/city_catalogs.py) | TI city catalog wire layouts, verified against original x86 readers. |
| [tio/protocol/city_services.py](../tio/protocol/city_services.py) | City-session services proven against this TI build. |
| [tio/protocol/clan_crests.py](../tio/protocol/clan_crests.py) | Original ti.exe crest59/5A and allianceAF06/AF07; native proof in evidence. |
| [tio/protocol/clan_ratings.py](../tio/protocol/clan_ratings.py) | Classic clan rating wire ABI, original Silver 6e70e0 / 6e6ef0. |
| [tio/protocol/clans.py](../tio/protocol/clans.py) | Native clan packets, silver.dll 6e6690..6e7150 (see CLANS.md). |
| [tio/protocol/enhancement.py](../tio/protocol/enhancement.py) | C8/2A item enhancement, original builder99f25c / writer6419a8. |
| [tio/protocol/equipment_batch.py](../tio/protocol/equipment_batch.py) | TIO emulator extension F6/v1; this is not an original game opcode. |
| [tio/protocol/equipment_templates.py](../tio/protocol/equipment_templates.py) | Original C5 equipment templates (silver.dll 92ec28, 92ee38, 646328). |
| [tio/protocol/health.py](../tio/protocol/health.py) | 4E status4 carries absolute current HP; native8c75b2 writes actor+6006. |
| [tio/protocol/hire.py](../tio/protocol/hire.py) | C2S63 selected candidate ID; original writer8c3c34, UI8ab9ae. |
| [tio/protocol/item_action.py](../tio/protocol/item_action.py) | Shared item action33 envelope, also reached from the Wear button. |
| [tio/protocol/item_batch.py](../tio/protocol/item_batch.py) | Original6B batch envelope. Mode/group action meanings remain unrecovered. |
| [tio/protocol/item_list.py](../tio/protocol/item_list.py) | Item-list request2F and verified empty ItemList30 response subset. |
| [tio/protocol/item_marks.py](../tio/protocol/item_marks.py) | S2C native30/6A mark metadata, readers63bd38/63e978 ->629860 UTF16 NUL. |
| [tio/protocol/known_mines.py](../tio/protocol/known_mines.py) | C8/3E TANetSendKnownMinesList, original RTTI and serializer658bc8. |
| [tio/protocol/login.py](../tio/protocol/login.py) | CONFIRMED LSAuthResult consumer: silver.dll preferred VA 0x87ce60. |
| [tio/protocol/mail.py](../tio/protocol/mail.py) | Original SILVER B7 mail ABI; selection/draft ids stay server authoritative. |
| [tio/protocol/mine_defuse.py](../tio/protocol/mine_defuse.py) | Original95965c ->659094 C8/40; not a mine-device entitlement. |
| [tio/protocol/mine_requests.py](../tio/protocol/mine_requests.py) | Original B0 checkpoint queue ABI, verified against silver.dll x86. |
| [tio/protocol/mining.py](../tio/protocol/mining.py) | Original silver.dll net3_Checkpoint835108 and its B0 serializers. |
| [tio/protocol/mode1.py](../tio/protocol/mode1.py) | Early ORANGE mode1 challenge09/reply0A, not the complete game transport. |
| [tio/protocol/night_vision_state.py](../tio/protocol/night_vision_state.py) | Explicit F9/v1 owner-only full snapshot for the NVG client toggle gate. |
| [tio/protocol/pet_info.py](../tio/protocol/pet_info.py) | PetInfo66 layouts proven by original8c4380 (bounded optional-state subset). |
| [tio/protocol/pet_state.py](../tio/protocol/pet_state.py) | Original8c3c94 emits67 actor:u32 and action:u32 (from byte DL). |
| [tio/protocol/player_auction.py](../tio/protocol/player_auction.py) | General player auction C8/08..0F, recovered from silver.dll 62d290..62e965. |
| [tio/protocol/player_top100.py](../tio/protocol/player_top100.py) | Original player standings: A4 builder77f74c, A5 reader77f788. |
| [tio/protocol/player_trade.py](../tio/protocol/player_trade.py) | Original Silver barter ABI: 84/86/88/8B requests, 85/87/89/8A/8C replies. |
| [tio/protocol/premium_shop.py](../tio/protocol/premium_shop.py) | Original city Gold shop: 76 request, 77 catalog, 78 purchase. |
| [tio/protocol/presence.py](../tio/protocol/presence.py) | Native chat rosters: C7 global; 4F/51 location, trade and help (7d02d8). |
| [tio/protocol/private_shops.py](../tio/protocol/private_shops.py) | Original AE private-store builders860a0c..860e50/readers860ed8..861160. |
| [tio/protocol/proficiency_decrease.py](../tio/protocol/proficiency_decrease.py) | Original GUI decrease routes through chat21's /decreaseability command. |
| [tio/protocol/public_profile.py](../tio/protocol/public_profile.py) | 68 request (96d568), A7/00 reader (96d7d0), original silver.dll. |
| [tio/protocol/quest_ack.py](../tio/protocol/quest_ack.py) | Original B8/10 ACK: dispatcher9CC548, reader9CC230 consumes a Cardinal. |
| [tio/protocol/ranked.py](../tio/protocol/ranked.py) | Original C6 TrueSkill builders/readers: silver 952bfc, 953038, 953d30, 953e5c. |
| [tio/protocol/rental.py](../tio/protocol/rental.py) | Original B40E/B40F/B410, silver.dll 8eb510/8ebca8/8eb4b0. |
| [tio/protocol/repair.py](../tio/protocol/repair.py) | Native repair writers 9905FC (7E) and 99F218 (C2/03). |
| [tio/protocol/sc_auction.py](../tio/protocol/sc_auction.py) | Proven original BD request builders89d5a0..89dd2c. |
| [tio/protocol/sc_auction_view.py](../tio/protocol/sc_auction_view.py) | Explicit emulator F8/v1 snapshots for the dormant original SC GUI. |
| [tio/protocol/sc_shop.py](../tio/protocol/sc_shop.py) | SC B4 protocol, recovered from silver.dll 655368/655bd0/8eb8d0. |
| [tio/protocol/server_list.py](../tio/protocol/server_list.py) | SILVER 0x87d1cc list06 and 0x87c76c request05. Field semantics stay conservative. |
| [tio/protocol/server_login.py](../tio/protocol/server_login.py) | SILVER87c7b4 builder07 /87d400 result08; eight bytes remain opaque. |
| [tio/protocol/shared_config.py](../tio/protocol/shared_config.py) | B9/01 manifest from SILVER 9d070c/9d0408; token semantics unconfirmed. |
| [tio/protocol/shop_purchase.py](../tio/protocol/shop_purchase.py) | Ordinary shop purchase request75, original builder9919c8. |
| [tio/protocol/shop_sale.py](../tio/protocol/shop_sale.py) | Sale: quote B806/B807 (8a0fe4/8a15a0), commit23 (99034c). |
| [tio/protocol/system_message.py](../tio/protocol/system_message.py) | Confirmed subset of TI F0 SystemMessage: town command98, integer argument. |
| [tio/protocol/tactical_marks.py](../tio/protocol/tactical_marks.py) | Original net3_Markers: B2/06 request and B2/07 notification. |
| [tio/protocol/town_info.py](../tio/protocol/town_info.py) | TI C8/2D subset confirmed by decoder64a3fc and a live client probe. |
| [tio/protocol/trace.py](../tio/protocol/trace.py) | Append-only JSONL records. Packet adjacency is linked without editing history. |
| [tio/protocol/transport.py](../tio/protocol/transport.py) | Initial TI ORANGE transport only, recovered from unpacked 0x1cd0/0x2710. |
| [tio/protocol/wagers.py](../tio/protocol/wagers.py) | Original main-room requests recovered from silver.dll a089f0/a08a50/a08ae4. |
| [tio/protocol/warehouse.py](../tio/protocol/warehouse.py) | WarehouseList6A, original63f60c/63ead4. |
| [tio/protocol/warehouse_capacity.py](../tio/protocol/warehouse_capacity.py) | Opt-in emulator FA/v1 warehouse UI snapshot; never an item operation. |
| [tio/protocol/warehouse_transfer.py](../tio/protocol/warehouse_transfer.py) | C2S6B original992294: two ordered arrays of instance/count pairs. |
| [tio/protocol/weather.py](../tio/protocol/weather.py) | FB/v1 cosmetic rain extension; independent of the F7 item snapshot. |
| [tio/protocol/world_bootstrap.py](../tio/protocol/world_bootstrap.py) | Confirmed SILVER18/1A wire layouts; unknown fields preserved. |
| [tio/pve_contracts.py](../tio/pve_contracts.py) | Durable, private cooperative clearance contracts. |
| [tio/ranked.py](../tio/ranked.py) | Two-side TrueSkill inference and transactional, match-wide rating receipts. |
| [tio/ranks.py](../tio/ranks.py) | Soldier ranks: manual pp.52–54, original PetInfo66 rank fields. |
| [tio/rating_completion.py](../tio/rating_completion.py) | Durable rating of fixed four-account Wall squads, separate from duel ratings. |
| [tio/rating_seasons.py](../tio/rating_seasons.py) | UTC calendar seasons, sealed only after their durable matches close. |
| [tio/rating_visibility.py](../tio/rating_visibility.py) | Keep server QA identities out of public standings, including character slots. |
| [tio/rental.py](../tio/rental.py) | Timed rentals. Absolute UTC deadlines are authoritative; wire time is seconds left. |
| [tio/repair.py](../tio/repair.py) | Atomic city repairs. Session selection never confers item ownership. |
| [tio/reward_policy.py](../tio/reward_policy.py) | Server-only arena inputs and exact, auditable credit calculations. |
| [tio/roster_progression.py](../tio/roster_progression.py) | Fresh-character starters, durable random city hires and tutorial progress. |
| [tio/sc_auction.py](../tio/sc_auction.py) | Shared Scandinavian SC auction, paid bids and durable prepaid autobots. |
| [tio/sc_pricing.py](../tio/sc_pricing.py) | Ready SC equipment costs more than its expected self-upgrade cost. |
| [tio/sc_shop.py](../tio/sc_shop.py) | Provisional Gold SC store with atomic inventory, stock and cart persistence. |
| [tio/services.py](../tio/services.py) | Original B1 services; permanent personal upgrades confirmed by the manual. |
| [tio/services_completion.py](../tio/services_completion.py) | Authoritative city services; joins the caller's shared SQLite transaction. |
| [tio/shooting_range.py](../tio/shooting_range.py) | Native practice lobby and persistent daily admission, separate from PvP rewards. |
| [tio/shop.py](../tio/shop.py) | Atomic native item shop purchases/sales on the shared account database. |
| [tio/shop_completion.py](../tio/shop_completion.py) | Manual shop completion; uncertain numeric rules are explicit versioned policy. |
| [tio/shop_errors.py](../tio/shop_errors.py) | Translate known shop rejections into the client's localized parameter error. |
| [tio/shot_geometry.py](../tio/shot_geometry.py) | TI CanTraceCells (ti.exe 6E1C88, legacy mode) sight rays in 32-unit cells. |
| [tio/social_completion.py](../tio/social_completion.py) | Public social views and accepted clan departures on shared SQLite authority. |
| [tio/squad.py](../tio/squad.py) | Persistent regular arena slots:0 available,1..3 selected;4 special/unfit. |
| [tio/survival_service.py](../tio/survival_service.py) | Survival search admission and cancellation for the original BA UI. |
| [tio/tactical_bot.py](../tio/tactical_bot.py) | Arena policy: bounded scavenging, treatment, and affordable fire/cover plans. |
| [tio/team_lobbies.py](../tio/team_lobbies.py) | Shared team assembly and FIFO matching. No automatic all-bot opponents. |
| [tio/team_ratings.py](../tio/team_ratings.py) | Durable rating of fixed two-account squads, separate from duel ratings. |
| [tio/team_scene.py](../tio/team_scene.py) | Combine real account squads into one field without changing saved IDs. |
| [tio/territories.py](../tio/territories.py) | Persisted Assault 4 windows, frozen four-account groups and territory claims. |
| [tio/training_bot.py](../tio/training_bot.py) | Deterministic training movement through the same authoritative move API. |
| [tio/travel_party.py](../tio/travel_party.py) | Durable, consent-based travel groups for distinct authenticated players. |
| [tio/visibility.py](../tio/visibility.py) | Actor visibility uses per-observer radius and original tile-class sight rays. |
| [tio/wagers.py](../tio/wagers.py) | Credit-only wager lobbies and durable, transaction-bound escrow. |
| [tio/wallets.py](../tio/wallets.py) | Persistent account starting funds; seeding never resets an existing wallet. |
| [tio/warehouse.py](../tio/warehouse.py) | Persistent private warehouse; explicit server operations, not wire6B routing. |
| [tio/warehouse_completion.py](../tio/warehouse_completion.py) | City warehouses without altering or reseeding any legacy item row. |
| [tio/warehouse_queries.py](../tio/warehouse_queries.py) | Recovered read requests, with explicit limits of missing clan/mail/mark state. |
| [tio/warehouse_service.py](../tio/warehouse_service.py) | Private warehouse requests; first6B list deposits, second withdraws. |
| [tio/weapon_effects.py](../tio/weapon_effects.py) | Effects with complete legacy item/ability definitions. |
| [tio/weapon_proficiency.py](../tio/weapon_proficiency.py) | Native damage factor, with explicitly provisional configurable training rules. |
| [tio/weapons.py](../tio/weapons.py) | Server combat metadata recovered from the legacy client items.cfg. |
| [tio/weather.py](../tio/weather.py) | Shared cosmetic weather; never grants visibility or mutates battle actors. |
| [tio/weight.py](../tio/weight.py) | Carried mass and overload; equipped items are included exactly once. |
| [tio/world_completion.py](../tio/world_completion.py) | Shared world rules, frozen coefficients, online prison and public top100. |
| [tio/world_encounters.py](../tio/world_encounters.py) | Distance-based, account-owned world encounters on the authoritative server. |

## registration/

| Файл | Назначение из docstring |
| --- | --- |
| [registration/__init__.py](../registration/__init__.py) | Optional self-registration website, separate from the game listener. |
| [registration/__main__.py](../registration/__main__.py) | См. код и вызывающие модули. |
| [registration/app.py](../registration/app.py) | См. код и вызывающие модули. |
| [registration/game_bridge.py](../registration/game_bridge.py) | Private website account adapter. Never publish this listener through nginx. |
| [registration/test_game_bridge.py](../registration/test_game_bridge.py) | Private adapter regressions with disposable game data, never hosted saves. |
| [registration/test_registration.py](../registration/test_registration.py) | См. код и вызывающие модули. |

## tools/

| Файл | Назначение из docstring |
| --- | --- |
| [tests/test_item_icons_hd.py](../tests/test_item_icons_hd.py) | HD item icon pipeline: classification, native mesh reading and framing. |
| [tools/aggregate_ui_scale_core_proof.py](../tools/aggregate_ui_scale_core_proof.py) | Aggregate offline proof provenance for the frozen 099 UI scale core. |
| [tools/apply_original_shop_prices.py](../tools/apply_original_shop_prices.py) | Rebuild ordinary/Premium shop prices from the 2008-2011 manual tables. |
| [tools/apply_portal_email_migration_remote.py](../tools/apply_portal_email_migration_remote.py) | Apply the bounded portal email migration after verifying hosted backups. |
| [tools/arena_boundaries_release.py](../tools/arena_boundaries_release.py) | Strict offline client-only boundary release predicates; no network or writes. |
| [tools/arena_boundaries_validation.py](../tools/arena_boundaries_validation.py) | Read-only exact published .3 SET/TILE/PNG validation; no game sessions. |
| [tools/arena_fog_validation.py](../tools/arena_fog_validation.py) | Version-bound validation for B1 native foreground; v1 evidence stays intact. |
| [tools/arena_surroundings_composition.py](../tools/arena_surroundings_composition.py) | Compose decorative arena props at their original pixel size. |
| [tools/arena_surroundings_deployment.py](../tools/arena_surroundings_deployment.py) | Shared local release constants; importing this module has no side effects. |
| [tools/arena_surroundings_layout.py](../tools/arena_surroundings_layout.py) | Distinct functional surroundings, using verified city sprites at 1:1. |
| [tools/arena_surroundings_native.py](../tools/arena_surroundings_native.py) | Encode decorative, noninteractive native TI TILE v2 and TI SET resources. |
| [tools/attest_hosted_world_completion.py](../tools/attest_hosted_world_completion.py) | Read-only final attestation of an already completed native world journey. |
| [tools/audit_battle_ground_resources.py](../tools/audit_battle_ground_resources.py) | Read-only inventory of installed ground.xml brush dependencies. |
| [tools/audit_weapon_attacks.py](../tools/audit_weapon_attacks.py) | Attack once with every catalog weapon on the real Combat engine. |
| [tools/audit_launcher_014_recovery_status.py](../tools/audit_launcher_014_recovery_status.py) | Read-only final service/timer/scratch audit after approved recovery capture. |
| [tools/audit_project_20261001.py](../tools/audit_project_20261001.py) | Read-only hosting inspection and isolated reproductions; never deploys. |
| [tools/audit_reservation_candidates.py](../tools/audit_reservation_candidates.py) | Read original candidate fragments without changing gameplay configuration. |
| [tools/audit_reservation_maps.py](../tools/audit_reservation_maps.py) | Audit every configured fragment and a reproducible sample of generated maps. |
| [tools/audit_unanswered_requests.py](../tools/audit_unanswered_requests.py) | Audit saved post-auth client requests and replay selected gaps in a temp DB. |
| [tools/balance_editor.py](../tools/balance_editor.py) | Run: python tools/balance_editor.py --open (Python standard library only). |
| [tools/balance_editor_core.py](../tools/balance_editor_core.py) | Isolated balance profiles. No game database or live catalog writes. |
| [tools/battle_actor_fixture.py](../tools/battle_actor_fixture.py) | Diagnostic actor from saved66 and equipped30 template IDs; combat incomplete. |
| [tools/battle_roster_fixture.py](../tools/battle_roster_fixture.py) | Prepare one diagnostic scene actor from a consistent server DB snapshot. |
| [tools/benchmark_battle_checkpoints.py](../tools/benchmark_battle_checkpoints.py) | Measure eight real-account slots across four authoritative test matches. |
| [tools/bind_world_release_evidence.py](../tools/bind_world_release_evidence.py) | Join successful runtime evidence to the exact executed native XML release. |
| [tools/build_ability_catalog.py](../tools/build_ability_catalog.py) | Import legacy ability parameters without inventing missing levels or prices. |
| [tools/build_arena_boundaries.py](../tools/build_arena_boundaries.py) | Compile the approved low A boundaries in native isometric coordinates. |
| [tools/build_arena_browsing_visible_native.py](../tools/build_arena_browsing_visible_native.py) | Freeze exact published853feb→native lobby navigation/colour presentation. |
| [tools/build_arena_browsing_visible_qa.py](../tools/build_arena_browsing_visible_qa.py) | Build separate keep-visible candidate/verifier/reviewer; old freezes intact. |
| [tools/build_arena_empty_roster_navigation_native.py](../tools/build_arena_empty_roster_navigation_native.py) | Freeze exact published853feb→native lobby navigation/colour presentation. |
| [tools/build_arena_lobby_navigation_native.py](../tools/build_arena_lobby_navigation_native.py) | Freeze exact published853feb→native lobby navigation/colour presentation. |
| [tools/build_arena_lobby_search_status_native.py](../tools/build_arena_lobby_search_status_native.py) | Freeze exact published853feb→native lobby navigation/colour presentation. |
| [tools/build_arena_screenshot_review.py](../tools/build_arena_screenshot_review.py) | Build a local gallery from unedited screenshots of hosted graphical battles. |
| [tools/build_arena_surroundings.py](../tools/build_arena_surroundings.py) | Export approved surroundings without nonlinear distortion. |
| [tools/build_avatar_types.py](../tools/build_avatar_types.py) | Extract female silhouette, dog and miner portraits from original atlases. |
| [tools/build_avatars.py](../tools/build_avatars.py) | Prepare three original-resource portraits; never modify installed game files. |
| [tools/build_battle_item_extension.py](../tools/build_battle_item_extension.py) | Prepare a reviewable catalog overlay; never modify shared/client files. |
| [tools/build_battle_ui_hd_assets.py](../tools/build_battle_ui_hd_assets.py) | Export original-design item masters and the reviewed battle glyph sheet. |
| [tools/build_battle_ui_hd_client.py](../tools/build_battle_ui_hd_client.py) | Compose the exact hosted client fixes and register reviewed publication ranges. |
| [tools/build_browsing_visible_bridge_static_qa.py](../tools/build_browsing_visible_bridge_static_qa.py) | Create a new revision of the offline bridge verifier; preserve prior reports. |
| [tools/build_city_scenery.py](../tools/build_city_scenery.py) | Import authored city fragments with cached-image native TILE door decoding. |
| [tools/build_contracts_city_assets.py](../tools/build_contracts_city_assets.py) | Pack the selected ImageGen city masters into separate native UI textures. |
| [tools/build_empty_roster_bridge_static_qa.py](../tools/build_empty_roster_bridge_static_qa.py) | Create separate bridge static verifier for the frozen actual-mode0 client. |
| [tools/build_empty_roster_navigation_native_qa.py](../tools/build_empty_roster_navigation_native_qa.py) | NEW actual-mode0 verifier/builder; all prior freezes remain immutable. |
| [tools/build_encounter_assets.py](../tools/build_encounter_assets.py) | Add isolated infected-dog bindings to the exact published client resources. |
| [tools/build_english_localization.py](../tools/build_english_localization.py) | Build an offline English resource pack from the inspected hosted client. |
| [tools/build_equipment_texture_release.py](../tools/build_equipment_texture_release.py) | Build an asset-only release from the hosted manifest and verified AI exports. |
| [tools/build_generated_avatars.py](../tools/build_generated_avatars.py) | Package original AI portraits for the native 4096-byte JPEG protocol. |
| [tools/build_global_map_assets.py](../tools/build_global_map_assets.py) | Package original ImageGen PNGs and an authoritative map layout. |
| [tools/build_item_fixture.py](../tools/build_item_fixture.py) | Import original local CFG records and build a local-priced ordinary shop. |
| [tools/build_legacy_degrain_assets.py](../tools/build_legacy_degrain_assets.py) | Export reviewed imagegen cleanups into unchanged native texture layouts. |
| [tools/build_legacy_lobbies_client.py](../tools/build_legacy_lobbies_client.py) | Compose the two verified native transformations into one reviewed release. |
| [tools/build_legacy_navigation_browse_ascii_client.py](../tools/build_legacy_navigation_browse_ascii_client.py) | Prepare the frozen .3 arena navigation and occupied-state colours, thirteen HUD textures and the native help line. |
| [tools/build_legacy_navigation_busy_ascii_client.py](../tools/build_legacy_navigation_busy_ascii_client.py) | Prepare the frozen .3 arena navigation and occupied-state colours, thirteen HUD textures and the native help line. |
| [tools/build_legacy_navigation_busy_client.py](../tools/build_legacy_navigation_busy_client.py) | Prepare the frozen .3 arena navigation and occupied-state colours, thirteen HUD textures and the native help line. |
| [tools/build_legacy_navigation_client.py](../tools/build_legacy_navigation_client.py) | Prepare the frozen .3 arena navigation and thirteen main-HUD textures. |
| [tools/build_legacy_navigation_empty_ascii_client.py](../tools/build_legacy_navigation_empty_ascii_client.py) | Prepare the frozen .3 arena navigation and occupied-state colours, thirteen HUD textures and the native help line. |
| [tools/build_legacy_navigation_help_client.py](../tools/build_legacy_navigation_help_client.py) | Prepare the frozen .3 arena navigation and thirteen main-HUD textures and the native lobby help line. |
| [tools/build_legacy_project_agreement_client.py](../tools/build_legacy_project_agreement_client.py) | Encode the final project agreement and build a scoped one-file legacy release. |
| [tools/build_legacy_server_status_native.py](../tools/build_legacy_server_status_native.py) | Reconstruct the immutable status/refresh candidate and exact public review. |
| [tools/build_legacy_status_client.py](../tools/build_legacy_status_client.py) | Prepare the frozen .2 Silver plus thirteen native textures, without publishing. |
| [tools/build_main_hud_degrain_assets.py](../tools/build_main_hud_degrain_assets.py) | Encode reviewed ImageGen HUD edits into unchanged native layouts. |
| [tools/build_menu_interface_assets.py](../tools/build_menu_interface_assets.py) | Prepare generated art for the client's existing sliced native UI resources. |
| [tools/build_mine_drill_ui_client.py](../tools/build_mine_drill_ui_client.py) | Compose mine hit testing and native icon API repairs from trusted .1 bytes. |
| [tools/build_native_door_grid.py](../tools/build_native_door_grid.py) | Assemble the bounded native door adapter used by TIO Launcher. |
| [tools/build_native_english_captions.py](../tools/build_native_english_captions.py) | Prepare bounded in-memory English captions for reviewed published DLLs. |
| [tools/build_native_lobby_departure_candidate.py](../tools/build_native_lobby_departure_candidate.py) | Isolate actual-hosted Team/Wall BA02 candidate plus native27 departure fix. |
| [tools/build_native_lobby_live_projection_candidate.py](../tools/build_native_lobby_live_projection_candidate.py) | Isolate a BA02 live projection candidate; never touch hosted/native clients. |
| [tools/build_native_lobby_original_names_candidate.py](../tools/build_native_lobby_original_names_candidate.py) | Read deployed sources and remove only appended Team/Wall Name decorations. |
| [tools/build_native_ui_fonts.py](../tools/build_native_ui_fonts.py) | Rasterize the selected Roboto Condensed face for the native font adapter. |
| [tools/build_rain_weather.py](../tools/build_rain_weather.py) | Build finite rain audio and the scoped native client patch from originals. |
| [tools/build_rental_catalog.py](../tools/build_rental_catalog.py) | Populate all rental-eligible client equipment; retain approved Gold prices. |
| [tools/build_reservation_map_review.py](../tools/build_reservation_map_review.py) | Read-only contest scene review; static conservative grid, not deployed gameplay. |
| [tools/build_sc_catalog.py](../tools/build_sc_catalog.py) | Build an explicitly provisional SC assortment from existing client items. |
| [tools/build_search_status_native_qa.py](../tools/build_search_status_native_qa.py) | Create NEW search-status verifier/builder; prior freeze files are untouched. |
| [tools/build_selected_ui_hd_icons.py](../tools/build_selected_ui_hd_icons.py) | Export selected classic-A native density sheets, retaining native chrome. |
| [tools/build_skills_fixture.py](../tools/build_skills_fixture.py) | Translate complete legacy value tables into the native skills.xml catalog. |
| [tools/build_texture_quality_client.py](../tools/build_texture_quality_client.py) | Prepare a scoped native client candidate; do not install or publish it. |
| [tools/build_tutorial_map.py](../tools/build_tutorial_map.py) | Import the installed original tutorial map; no shared catalogue mutation. |
| [tools/build_ui_hd_asset_previews.py](../tools/build_ui_hd_asset_previews.py) | Compose repeatable font/icon concepts, never client or hosting assets. |
| [tools/build_ui_hd_client.py](../tools/build_ui_hd_client.py) | Build the selected classic icons + Roboto font client from pinned release12. |
| [tools/build_ui_hd_observer.py](../tools/build_ui_hd_observer.py) | Bind a bounded read-only HD observer to the existing owned display trace. |
| [tools/build_ui_hd_package.py](../tools/build_ui_hd_package.py) | Assemble only the frozen selected HD client files for the update publisher. |
| [tools/build_ui_hd_specimens.py](../tools/build_ui_hd_specimens.py) | Build compact scale specimens from real TTFs and reviewed icon exports. |
| [tools/build_ui_modernization_client.py](../tools/build_ui_modernization_client.py) | Build only the reviewed .11 -> UI scale -> controls -> portrait chain. |
| [tools/build_visual_asset_catalog.py](../tools/build_visual_asset_catalog.py) | Read-only visual catalog of original setting textures and model references. |
| [tools/build_world_completion_overlay.py](../tools/build_world_completion_overlay.py) | Reviewable world XML overlay; never mutates published or shared zones XML. |
| [tools/capture_launcher_014_offsite.py](../tools/capture_launcher_014_offsite.py) | One explicit fresh encrypted capture followed by independent local proof. |
| [tools/capture_loaded_orange.py](../tools/capture_loaded_orange.py) | Launch owned TIO process, block network connects, dump its loaded ORANGE image. |
| [tools/capture_shared_mines_recovery.py](../tools/capture_shared_mines_recovery.py) | Capture and independently verify deployed shared-mines recovery without local plaintext. |
| [tools/capture_stage11_services_wire.py](../tools/capture_stage11_services_wire.py) | Synthetic DTO fixtures from exact frozen public stage11-r5, never player saves. |
| [tools/capture_stage4_recovery.py](../tools/capture_stage4_recovery.py) | Capture and independently verify Stage4 recovery without local plaintext. |
| [tools/catalog_city_resources.py](../tools/catalog_city_resources.py) | Inventory resource families; deliberately do not infer city ownership from paths. |
| [tools/check_arena_search_status_native.py](../tools/check_arena_search_status_native.py) | Bounded original full-renderer status2 regression check; no frozen edits. |
| [tools/check_bank_operations.py](../tools/check_bank_operations.py) | Stage bank-command changes over the inspected hosted source and run checks. |
| [tools/check_bank_trade_release.py](../tools/check_bank_trade_release.py) | Build and check both prepared patches against a fresh production snapshot. |
| [tools/check_battle_screen_fixes.py](../tools/check_battle_screen_fixes.py) | Check the screenshot fixes on an isolated copy of the actual hosted runtime. |
| [tools/check_bot_credit_rewards.py](../tools/check_bot_credit_rewards.py) | Check bot credit rewards on an isolated copy of the actual hosted runtime. |
| [tools/check_bot_finishing.py](../tools/check_bot_finishing.py) | Check the bot finishing on an isolated copy of the actual hosted runtime. |
| [tools/check_game_operations.py](../tools/check_game_operations.py) | Validate a scoped refactor against the inspected hosted runtime snapshot. |
| [tools/check_tactical_bots.py](../tools/check_tactical_bots.py) | Check the bot patch on an isolated copy of the actual hosted runtime. |
| [tools/check_trade_operations.py](../tools/check_trade_operations.py) | Check scoped market refactor over the captured current hosted runtime. |
| [tools/check_trade_qa_cleanup.py](../tools/check_trade_qa_cleanup.py) | Check the hosted QA cleanup against disposable local SQLite fixtures. |
| [tools/cleanup_battle_screen_fixes_qa.py](../tools/cleanup_battle_screen_fixes_qa.py) | Remove only orphan receipts for matches proven by the four owned QA reports. |
| [tools/cleanup_bot_credit_rewards_qa.py](../tools/cleanup_bot_credit_rewards_qa.py) | Remove only orphan receipts for matches proven by the four owned QA reports. |
| [tools/cleanup_bot_finishing_qa.py](../tools/cleanup_bot_finishing_qa.py) | Remove only orphan receipts for matches proven by the four owned QA reports. |
| [tools/cleanup_hosted_qa.py](../tools/cleanup_hosted_qa.py) | Scoped cleanup requested on 2026-10-12; preserve all ordinary player rows. |
| [tools/cleanup_ranked_qa.py](../tools/cleanup_ranked_qa.py) | Remove rating-only QA entries from this stage's recorded fresh accounts. |
| [tools/cleanup_tactical_bot_qa.py](../tools/cleanup_tactical_bot_qa.py) | Remove only orphan receipts for matches proven by the four owned QA reports. |
| [tools/collect_evidence.py](../tools/collect_evidence.py) | Persist exact x86 bytes/disassembly, jump tables, and resource structural diffs. |
| [tools/compile_boundary_stone_atlas.py](../tools/compile_boundary_stone_atlas.py) | Slice generated RGBA atlas and normalize pixel density uniformly. |
| [tools/complete_english_server_messages.py](../tools/complete_english_server_messages.py) | Complete typed status/concatenated messages after the resource publication. |
| [tools/configure_portal_resend_remote.py](../tools/configure_portal_resend_remote.py) | Configure Resend HTTPS without putting its key in arguments or reports. |
| [tools/configure_portal_turnstile_remote.py](../tools/configure_portal_turnstile_remote.py) | Configure production Turnstile without printing or passing keys in arguments. |
| [tools/contracts_live_native_test.py](../tools/contracts_live_native_test.py) | Narrow local QA driver for already authenticated, owned native clients. |
| [tools/contracts_live_repro.py](../tools/contracts_live_repro.py) | Restart only the two owned loopback fixtures and observe native packet metadata. |
| [tools/contracts_native_probe.py](../tools/contracts_native_probe.py) | Bounded, offline x86 proofs for Contracts client research. |
| [tools/contracts_native_research.py](../tools/contracts_native_research.py) | Read-only Contracts investigation of the original Silver build. |
| [tools/deploy_admission_capacity_remote.py](../tools/deploy_admission_capacity_remote.py) | Run on the known hosting target with the narrowly scoped patch archive. |
| [tools/deploy_arena_gears_remote.py](../tools/deploy_arena_gears_remote.py) | Run on the known hosting target with the narrowly scoped patch archive. |
| [tools/deploy_arena_surroundings_remote.py](../tools/deploy_arena_surroundings_remote.py) | Guarded five-file hosted update plus new immutable surroundings resources. |
| [tools/deploy_avatar_types.py](../tools/deploy_avatar_types.py) | Validate and publish native avatar catalog, assignments and original art. |
| [tools/deploy_avatars.py](../tools/deploy_avatars.py) | Validate and publish native avatar catalog, assignments and original art. |
| [tools/deploy_backup_tools_remote.py](../tools/deploy_backup_tools_remote.py) | Guarded operational-file installation for Stage3 backups, without game restart. |
| [tools/deploy_bank_gateway_remote.py](../tools/deploy_bank_gateway_remote.py) | Install disabled Stripe gateway with guarded protected config and rollback. |
| [tools/deploy_battle_core_remote.py](../tools/deploy_battle_core_remote.py) | Run on the known hosting target with the narrowly scoped patch archive. |
| [tools/deploy_battle_exchange_remote.py](../tools/deploy_battle_exchange_remote.py) | Run on the known hosting target with the narrowly scoped patch archive. |
| [tools/deploy_battle_recovery_remote.py](../tools/deploy_battle_recovery_remote.py) | Run on the known hosting target with the narrowly scoped patch archive. |
| [tools/deploy_battle_rewards_remote.py](../tools/deploy_battle_rewards_remote.py) | Run on the known hosting target with the narrowly scoped patch archive. |
| [tools/deploy_battle_safety_remote.py](../tools/deploy_battle_safety_remote.py) | Run on the known hosting target with the narrowly scoped patch archive. |
| [tools/deploy_battle_turn_remote.py](../tools/deploy_battle_turn_remote.py) | Run on the known hosting target with the narrowly scoped patch archive. |
| [tools/deploy_chat_presence_remote.py](../tools/deploy_chat_presence_remote.py) | Run on the known hosting target with the narrowly scoped patch archive. |
| [tools/deploy_cities_remote.py](../tools/deploy_cities_remote.py) | Run on the known hosting target with the narrowly scoped patch archive. |
| [tools/deploy_city_scenery.py](../tools/deploy_city_scenery.py) | Scoped server-only TrueSkill whole-map update; preserve all hosted player rows. |
| [tools/deploy_clan_warfare.py](../tools/deploy_clan_warfare.py) | Guarded clan-warfare code deployment preserving every hosted account/save. |
| [tools/deploy_clans_remote.py](../tools/deploy_clans_remote.py) | Run on the known hosting target with the narrowly scoped patch archive. |
| [tools/deploy_contest_maps.py](../tools/deploy_contest_maps.py) | Scoped server-only TrueSkill whole-map update; preserve all hosted player rows. |
| [tools/deploy_corpse_visibility_remote.py](../tools/deploy_corpse_visibility_remote.py) | Run on the known hosting target with the narrowly scoped patch archive. |
| [tools/deploy_durability_remote.py](../tools/deploy_durability_remote.py) | Run on the known hosting target with the narrowly scoped patch archive. |
| [tools/deploy_encounter_return_remote.py](../tools/deploy_encounter_return_remote.py) | Candidate checks and guarded four-file hosted overlay; never upload a DB. |
| [tools/deploy_encounters_remote.py](../tools/deploy_encounters_remote.py) | Guarded hosted update: remote DB/code/config/client backups, no local saves. |
| [tools/deploy_equipment_textures_remote.py](../tools/deploy_equipment_textures_remote.py) | Back up the hosted database/code, then atomically publish immutable client assets. |
| [tools/deploy_fog_lobbies_remote.py](../tools/deploy_fog_lobbies_remote.py) | Run on the known hosting target with the narrowly scoped patch archive. |
| [tools/deploy_forest_remote.py](../tools/deploy_forest_remote.py) | Guarded hosted update: remote DB/code/config/client backups, no local saves. |
| [tools/deploy_game_operations_remote.py](../tools/deploy_game_operations_remote.py) | Scoped remote deployment; never uploads/restores player data. Run on VPS. |
| [tools/deploy_game_tls_remote.py](../tools/deploy_game_tls_remote.py) | Guarded code-only game TLS rollout on the documented existing VPS. |
| [tools/deploy_gameplay_completion.py](../tools/deploy_gameplay_completion.py) | Scoped gameplay updates: guarded sources, fresh hosted backups, no save upload. |
| [tools/deploy_generated_avatars.py](../tools/deploy_generated_avatars.py) | Validate against live code, back up live saves, publish a scoped avatar update. |
| [tools/deploy_ground_loot_remote.py](../tools/deploy_ground_loot_remote.py) | Run on the known hosting target with the narrowly scoped patch archive. |
| [tools/deploy_legacy_lobby_projection.py](../tools/deploy_legacy_lobby_projection.py) | Prepare/apply only the reviewed native lobby rows under a narrow city guard. |
| [tools/deploy_login_denials.py](../tools/deploy_login_denials.py) | Inspect and deploy exactly six authentication files; never upload save data. |
| [tools/deploy_login_display_remote.py](../tools/deploy_login_display_remote.py) | Run on the known hosting target with the narrowly scoped patch archive. |
| [tools/deploy_menu_interface_remote.py](../tools/deploy_menu_interface_remote.py) | Publish a validated UI-only archive without restarting the hosted game service. |
| [tools/deploy_player_statistics_remote.py](../tools/deploy_player_statistics_remote.py) | Run on the known hosting target with the narrowly scoped patch archive. |
| [tools/deploy_player_trade_remote.py](../tools/deploy_player_trade_remote.py) | Validate and deploy only reviewed barter files over the inspected hosted code. |
| [tools/deploy_portal_stage3_remote.py](../tools/deploy_portal_stage3_remote.py) | Publish a prebuilt portal release while preserving hosted saves and config. |
| [tools/deploy_premium_remote.py](../tools/deploy_premium_remote.py) | Run on the known hosting target with the narrowly scoped patch archive. |
| [tools/deploy_rain_weather.py](../tools/deploy_rain_weather.py) | Review, validate and publish the scoped hosted throwable release. |
| [tools/deploy_ranked_remote.py](../tools/deploy_ranked_remote.py) | Run on the known hosting target with the narrowly scoped patch archive. |
| [tools/deploy_rating_chat_fix.py](../tools/deploy_rating_chat_fix.py) | Deploy the public mining rating query fix without replacing hosted saves. |
| [tools/deploy_reservation_crate_alpha_remote.py](../tools/deploy_reservation_crate_alpha_remote.py) | Back up the live host and publish a two-texture release without restarting it. |
| [tools/deploy_reservation_maps_remote.py](../tools/deploy_reservation_maps_remote.py) | Run on the known hosting target with the narrowly scoped patch archive. |
| [tools/deploy_reservation_remote.py](../tools/deploy_reservation_remote.py) | Guarded hosted update: remote DB/code/config/client backups, no local saves. |
| [tools/deploy_services_auction_remote.py](../tools/deploy_services_auction_remote.py) | Run on the known hosting target with the narrowly scoped patch archive. |
| [tools/deploy_shared_mines.py](../tools/deploy_shared_mines.py) | Prepare/review guarded shared-mines code deployment; deploy requires explicit operator action. |
| [tools/deploy_shop_prices_remote.py](../tools/deploy_shop_prices_remote.py) | Run on the known hosting target with the narrowly scoped patch archive. |
| [tools/deploy_stage4_economy.py](../tools/deploy_stage4_economy.py) | Guarded code-only economy deployment; never uploads or restores player data. |
| [tools/deploy_stage7.py](../tools/deploy_stage7.py) | Guarded stage7 code deployment preserving every hosted account/save. |
| [tools/deploy_team_start_remote.py](../tools/deploy_team_start_remote.py) | Run on the known hosting target with the narrowly scoped patch archive. |
| [tools/deploy_throwable_effects.py](../tools/deploy_throwable_effects.py) | Review, validate and publish the scoped hosted throwable release. |
| [tools/deploy_turn_timer_remote.py](../tools/deploy_turn_timer_remote.py) | Run on the known hosting target with the narrowly scoped patch archive. |
| [tools/deploy_tutorial_dialogues.py](../tools/deploy_tutorial_dialogues.py) | Scoped server-only tutorial ACK update; preserve all hosted player rows. |
| [tools/deploy_ui_regressions_remote.py](../tools/deploy_ui_regressions_remote.py) | Run on the known hosting target with the narrowly scoped patch archive. |
| [tools/deploy_warehouse_queries_remote.py](../tools/deploy_warehouse_queries_remote.py) | Run on the known hosting target with the narrowly scoped patch archive. |
| [tools/deploy_weapon_effects_remote.py](../tools/deploy_weapon_effects_remote.py) | Run on the known hosting target with the narrowly scoped patch archive. |
| [tools/diagnose_owned_d_fixture_candidate.py](../tools/diagnose_owned_d_fixture_candidate.py) | Replay the failed reviewed fixture on an isolated remote backup copy only. |
| [tools/diagnose_owned_d_fixture_candidate_v2.py](../tools/diagnose_owned_d_fixture_candidate_v2.py) | Replay the failed reviewed fixture on an isolated remote backup copy only. |
| [tools/diagnose_public_regression_failures.py](../tools/diagnose_public_regression_failures.py) | Classify isolated public-suite failures; never access hosted accounts. |
| [tools/diagnose_public_regression_tcp.py](../tools/diagnose_public_regression_tcp.py) | Inspect temporary authoritative state after three failed native TCP assertions. |
| [tools/diagnose_trade_auction_hosted.py](../tools/diagnose_trade_auction_hosted.py) | Diagnose the reported 1000-credit exchange and auction visibility; no code deployment. |
| [tools/dismiss_owned_negative_qa_recruit.py](../tools/dismiss_owned_negative_qa_recruit.py) | Prepare owned D's negative GUI case using a genuine hosted dismissal. |
| [tools/encounter_scene.py](../tools/encounter_scene.py) | An infected dog pack on an original outdoor map, with persisted player gear. |
| [tools/equipment_texture_assets.py](../tools/equipment_texture_assets.py) | Inventory the exact hosted equipment resources; never use local player data. |
| [tools/equipment_texture_export.py](../tools/equipment_texture_export.py) | Register AI texture output to original UVs and export native-compatible resources. |
| [tools/export_native_font_atlas.py](../tools/export_native_font_atlas.py) | Offline native TI bitmap-font prototypes, with unchanged logical metrics. |
| [tools/export_ui_hd_icon_assets.py](../tools/export_ui_hd_icon_assets.py) | Export generated 4x4 icon masters into reviewable density/source packs. |
| [tools/extract_arena_boundary_palette.py](../tools/extract_arena_boundary_palette.py) | Extract original low boundary materials at 1:1; no runtime or server edits. |
| [tools/extract_original_arena_prop_palette.py](../tools/extract_original_arena_prop_palette.py) | Decode original native prop pixels at1:1; never resize or export runtime assets. |
| [tools/finalize_arena_boundaries_verification.py](../tools/finalize_arena_boundaries_verification.py) | Bind release .3 to 25 original native captures and final read-only health. |
| [tools/finalize_arena_fog_verification.py](../tools/finalize_arena_fog_verification.py) | Bind release .2 to completed native GUI captures and fresh read-only health. |
| [tools/finalize_arena_surroundings_verification.py](../tools/finalize_arena_surroundings_verification.py) | Bind completed release evidence to a fresh read-only hosted health check. |
| [tools/finalize_bot_credit_rewards_checks.py](../tools/finalize_bot_credit_rewards_checks.py) | Audit deployed sources, service and exact successful/failed QA cleanup. |
| [tools/finalize_frozen_public_release.py](../tools/finalize_frozen_public_release.py) | Create a root-reviewed net release without changing the delivered freeze. |
| [tools/finalize_gameplay_completion.py](../tools/finalize_gameplay_completion.py) | Bind completed hosted gameplay evidence and update the local progress record. |
| [tools/finalize_legacy_lobbies_release.py](../tools/finalize_legacy_lobbies_release.py) | Aggregate immutable automated evidence for the deployed 0.1.6 release. |
| [tools/finalize_legacy_lobbies_validation.py](../tools/finalize_legacy_lobbies_validation.py) | Record resolved fixture setup failures while preserving original test reports. |
| [tools/finalize_steam_package.py](../tools/finalize_steam_package.py) | Finalize the tested Steam candidate and archive without any Steam publication. |
| [tools/finalize_ui_hd_review_manifest.py](../tools/finalize_ui_hd_review_manifest.py) | Freeze review provenance and aggregate existing offline asset evidence. |
| [tools/forest_biomes_assets.py](../tools/forest_biomes_assets.py) | Verified published inputs, non-destructive biome resource copies and texture build. |
| [tools/freeze_arena_browsing_visible.py](../tools/freeze_arena_browsing_visible.py) | Freeze the scoped real-Show correction and all byte/source evidence. |
| [tools/freeze_arena_search_delta.py](../tools/freeze_arena_search_delta.py) | Prove NEW search-status freeze composes over immutable afaa evidence. |
| [tools/freeze_empty_roster_navigation.py](../tools/freeze_empty_roster_navigation.py) | Freeze actual-mode0 composition, actual entry proof and source dependencies. |
| [tools/freeze_native_lobby_departure.py](../tools/freeze_native_lobby_departure.py) | Freeze isolated hosted-source departure candidate and exact bounded evidence. |
| [tools/freeze_native_lobby_live_projection.py](../tools/freeze_native_lobby_live_projection.py) | Freeze125 checks, native BA02/BA06 and unchanged original25/27 TCP streams. |
| [tools/freeze_native_lobby_original_names.py](../tools/freeze_native_lobby_original_names.py) | Freeze original captain Name only, wire geometry,600 sources and111 checks. |
| [tools/freeze_rating_completion_candidate.py](../tools/freeze_rating_completion_candidate.py) | Pin a reviewable public rating overlay; retain earlier proof artifacts. |
| [tools/freeze_ratings_portal_candidate.py](../tools/freeze_ratings_portal_candidate.py) | Freeze read-only rating adapters on pinned public gameplay/city sources. |
| [tools/freeze_stage34_portal_integration.py](../tools/freeze_stage34_portal_integration.py) | Freeze a reviewed portal overlay after its isolated validation succeeds. |
| [tools/heal_owned_surroundings_fixture.py](../tools/heal_owned_surroundings_fixture.py) | Heal only the existing randomly named surroundings QA fixture while offline. |
| [tools/hold_owned_b_legacy_lobby_tls.py](../tools/hold_owned_b_legacy_lobby_tls.py) | One owned B TLS actor for real A/C GUI capacity checks; control-file commands only. |
| [tools/hosted_graphical_qa_bridge.py](../tools/hosted_graphical_qa_bridge.py) | Own graphical clients, genuine hosted native authentication, secrets on stdin. |
| [tools/hosted_new_player_graphical_qa.py](../tools/hosted_new_player_graphical_qa.py) | Observe genuinely clean launcher installs using only proven-owned QA logins. |
| [tools/hosted_normal_ti_tls_graphical_qa.py](../tools/hosted_normal_ti_tls_graphical_qa.py) | Owned TLS QA through the original TI Unicode connection adapter. |
| [tools/hosted_stage9_graphical_qa.py](../tools/hosted_stage9_graphical_qa.py) | Strict owned-copy sync and attach-only adapter for launcher 0.1.4. |
| [tools/hosted_stage9_graphical_qa_revision2.py](../tools/hosted_stage9_graphical_qa_revision2.py) | Owned QA revision2: early closed connection gate and fail-closed auth guards. |
| [tools/hosted_stage9_graphical_qa_revision3.py](../tools/hosted_stage9_graphical_qa_revision3.py) | Owned QA revision3: early closed connection gate and fail-closed auth guards. |
| [tools/hosted_tls_graphical_qa.py](../tools/hosted_tls_graphical_qa.py) | Attach observation/owned credentials to production-launcher TLS QA clients. |
| [tools/import_achievements.py](../tools/import_achievements.py) | Import the original localization; only verified manual prizes are mapped. |
| [tools/import_arena_fragments.py](../tools/import_arena_fragments.py) | Import TI SET v2 (including ZIP) footprints, native doors and provenance. |
| [tools/import_assault_maps.py](../tools/import_assault_maps.py) | Import the original Assault4 three-flag SET scenes; no player data. |
| [tools/import_mine_maps.py](../tools/import_mine_maps.py) | Import original full 60x60 mine scenes; keep resource basenames unchanged. |
| [tools/import_weapon_catalog.py](../tools/import_weapon_catalog.py) | Import legacy client combat values without inventing missing reload costs. |
| [tools/inspect_admission_capacity_hosting.py](../tools/inspect_admission_capacity_hosting.py) | Read-only post-update source, service, database and preservation checks. |
| [tools/inspect_arena_boundaries_hosting.py](../tools/inspect_arena_boundaries_hosting.py) | Capture only read-only hosted .2 inputs for a future boundary .3 release. |
| [tools/inspect_arena_gears_hosting.py](../tools/inspect_arena_gears_hosting.py) | Read-only final parity, accounts/saves, service and recovery verification. |
| [tools/inspect_arena_surroundings_hosting.py](../tools/inspect_arena_surroundings_hosting.py) | Capture a fresh read-only hosted baseline; no accounts, uploads or deployment. |
| [tools/inspect_battle_recovery_hosting.py](../tools/inspect_battle_recovery_hosting.py) | Read-only post-update source, service, database and preservation checks. |
| [tools/inspect_battle_safety_hosting.py](../tools/inspect_battle_safety_hosting.py) | Read-only post-update source, service, database and preservation checks. |
| [tools/inspect_battle_turn_hosting.py](../tools/inspect_battle_turn_hosting.py) | Read-only final parity, accounts/saves, service and recovery verification. |
| [tools/inspect_cfg.py](../tools/inspect_cfg.py) | Follow direct x86 branches in a mapped image, skipping jump-over junk bytes. |
| [tools/inspect_cities_hosting.py](../tools/inspect_cities_hosting.py) | Read-only final parity, accounts/saves, service and recovery verification. |
| [tools/inspect_clan_warfare.py](../tools/inspect_clan_warfare.py) | Read-only hosted clan-warfare baseline; no account or credential payloads. |
| [tools/inspect_contracts_live_checkpoint.py](../tools/inspect_contracts_live_checkpoint.py) | Read-only, checksum-verified audit of the local cooperative battle journal. |
| [tools/inspect_encounters_after.py](../tools/inspect_encounters_after.py) | Read-only hosted encounter health report; no account secrets. |
| [tools/inspect_encounters_hosting.py](../tools/inspect_encounters_hosting.py) | Read actual hosted sources/update manifest; preserve them before editing. |
| [tools/inspect_game_tls_readiness.py](../tools/inspect_game_tls_readiness.py) | Read listener and certificate metadata only; never read private keys. |
| [tools/inspect_gameplay_completion.py](../tools/inspect_gameplay_completion.py) | Read current hosted hashes and save counts before a scoped gameplay release. |
| [tools/inspect_hosted_graphical_qa_state.py](../tools/inspect_hosted_graphical_qa_state.py) | Read-only state snapshot from an explicitly owned hosted native QA PID. |
| [tools/inspect_hosted_owned_inventory.py](../tools/inspect_hosted_owned_inventory.py) | Read owned QA inventory and foreign-account fingerprints without secrets. |
| [tools/inspect_legacy_lobbies_release.py](../tools/inspect_legacy_lobbies_release.py) | Read the actual hosted native release and bounded server sources. |
| [tools/inspect_legacy_negative_fixture_readonly.py](../tools/inspect_legacy_negative_fixture_readonly.py) | Read only: inspect owned D roster against the pre-GUI negative fixture backup. |
| [tools/inspect_legacy_online_sessions.py](../tools/inspect_legacy_online_sessions.py) | Read-only aggregate sockets/heartbeat and hashed account journal inspection. |
| [tools/inspect_native_tls_route.py](../tools/inspect_native_tls_route.py) | Bounded read-only route inspection of one launcher-owned native game. |
| [tools/inspect_new_player_qa.py](../tools/inspect_new_player_qa.py) | Read-only hosted snapshots for the two approved new-player GUI accounts. |
| [tools/inspect_original_arena_decor.py](../tools/inspect_original_arena_decor.py) | Inventory original SHA-matching city sprites for composition without stretching. |
| [tools/inspect_owned_checkpoint_readonly.py](../tools/inspect_owned_checkpoint_readonly.py) | Inspect only checkpoint timing and table shape, without exposing battle payloads. |
| [tools/inspect_owned_inventory_layout.py](../tools/inspect_owned_inventory_layout.py) | One bounded read-only category-layout diagnostic for the exact owned QA PID. |
| [tools/inspect_owned_native_load_state.py](../tools/inspect_owned_native_load_state.py) | Read five known loading flags from two currently authenticated own QA clients. |
| [tools/inspect_pe.py](../tools/inspect_pe.py) | Read-only PE strings, exports, xrefs and x86 disassembly (preferred VAs). |
| [tools/inspect_ranked_hosting.py](../tools/inspect_ranked_hosting.py) | Verify live source parity, integrity and preservation of pre-update accounts. |
| [tools/inspect_recent_game_service.py](../tools/inspect_recent_game_service.py) | Read service health and non-sensitive recent event/error counters. |
| [tools/inspect_shared_mines.py](../tools/inspect_shared_mines.py) | Read-only shared-mines baseline; aggregate SQL only, no account rows/secrets. |
| [tools/inspect_shop_release_remote.py](../tools/inspect_shop_release_remote.py) | Inspect shop candidate baseline with explicit transport diagnostics. |
| [tools/inspect_shot_grid_live.py](../tools/inspect_shot_grid_live.py) | Read-only snapshot of native actor coordinates and sight/collision cells. |
| [tools/inspect_stage4_economy.py](../tools/inspect_stage4_economy.py) | Read-only hosted economy baseline; reports aggregate data, never credentials. |
| [tools/inspect_stage7.py](../tools/inspect_stage7.py) | Read-only hosted Stage7 baseline; public sources and aggregate DB counts. |
| [tools/install_bank_trade_release.py](../tools/install_bank_trade_release.py) | Install the checked combined release, using protected remote backups only. |
| [tools/install_global_map_client.py](../tools/install_global_map_client.py) | Install only the reviewed map release into the existing selected client. |
| [tools/integrate_services_ratings_portal.py](../tools/integrate_services_ratings_portal.py) | Apply only pinned new files and three reviewed portal edits. |
| [tools/inventory.py](../tools/inventory.py) | Reproducible client inventory and TI/AZT resource/string comparison. |
| [tools/item_icons_hd/__init__.py](../tools/item_icons_hd/__init__.py) | Package marker. |
| [tools/item_icons_hd/build_manifest.py](../tools/item_icons_hd/build_manifest.py) | Write assets/item-icons-hd-v1/manifest.json from the delivered catalogue. |
| [tools/item_icons_hd/catalog.py](../tools/item_icons_hd/catalog.py) | Decide how each inventory item gets a high-resolution icon. |
| [tools/item_icons_hd/export.py](../tools/item_icons_hd/export.py) | Deterministic size exports from one approved master icon (Pillow). |
| [tools/item_icons_hd/framing.py](../tools/item_icons_hd/framing.py) | Pure camera framing for icon renders; shared by Blender and tests. |
| [tools/item_icons_hd/mesh.py](../tools/item_icons_hd/mesh.py) | Read native MDJX geometry for icon rendering: skinned and static variants. |
| [tools/item_icons_hd/preview.py](../tools/item_icons_hd/preview.py) | Quick software preview of icon framing without Blender (numpy + Pillow). |
| [tools/item_icons_hd/render_blender.py](../tools/item_icons_hd/render_blender.py) | Render reference icons from native models. Run inside Blender 3.6+/4.x. |
| [tools/item_icons_hd/render_options.py](../tools/item_icons_hd/render_options.py) | Resolve render CLI paths before Blender scene initialization. |
| [tools/loopback_exchange.py](../tools/loopback_exchange.py) | Bounded loopback experiment for the statically recovered initial challenge. |
| [tools/manage_launcher_archive.py](../tools/manage_launcher_archive.py) | Inspect, prepare or publish a compressed package of the exact hosted release. |
| [tools/manage_mine_claims.py](../tools/manage_mine_claims.py) | Explicit, local checkpoint ownership administration; no SSH or native bypass. |
| [tools/manage_team_seasons.py](../tools/manage_team_seasons.py) | Read/close team-rating seasons locally on the authoritative database. |
| [tools/manage_territories.py](../tools/manage_territories.py) | Read the authoritative territory schedule, claims and event receipts. |
| [tools/mine_scene_fixture.py](../tools/mine_scene_fixture.py) | Temporarily remove the authored geyser in mine03; preserve original bytes. |
| [tools/mining_item_fixture.py](../tools/mining_item_fixture.py) | Restore missing mining bindings from native IDs and installed model assets. |
| [tools/mining_scene.py](../tools/mining_scene.py) | Prepare native mode7 and original resource100 sick miners; no mirrored gear. |
| [tools/model_stage4_economy.py](../tools/model_stage4_economy.py) | Source-backed local economy scenarios, never a hosted/graphical QA claim. |
| [tools/moderate_prison.py](../tools/moderate_prison.py) | Trusted local operator interface for an explicit online Prison sentence. |
| [tools/native_texture_contract.py](../tools/native_texture_contract.py) | Stdlib-only native texture structure/alpha contract for scoped publication. |
| [tools/native_texture_contract_hud.py](../tools/native_texture_contract_hud.py) | Self-contained stdlib contract for the main HUD BMP32/PNG/JPEG package. |
| [tools/new_player_action_observer.py](../tools/new_player_action_observer.py) | Passive native action evidence for the exact published new-player client. |
| [tools/normalize_armor_models.py](../tools/normalize_armor_models.py) | Bridge legacy CFG armor names to installed client meshes. |
| [tools/normalize_equipment_effects.py](../tools/normalize_equipment_effects.py) | Translate legacy effect fields to the native XML tooltip bonus records. |
| [tools/normalize_item_icons.py](../tools/normalize_item_icons.py) | Replace eight missing legacy icon references with installed client assets. |
| [tools/normalize_item_stacking.py](../tools/normalize_item_stacking.py) | Publish the user's stacking policy through native item metadata. |
| [tools/normalize_weapon_xml.py](../tools/normalize_weapon_xml.py) | Map legacy weapon stats into the bindings used by the original XML reader. |
| [tools/observe_arena_camera.py](../tools/observe_arena_camera.py) | Read-only camera telemetry for an existing HostedGraphicalQaBridge session. |
| [tools/observe_legacy_server_list_tls.py](../tools/observe_legacy_server_list_tls.py) | Read-only original05/06 TLS observer using the existing owned QA account B. |
| [tools/observe_native_login_route.py](../tools/observe_native_login_route.py) | Observe one explicitly selected player game's login route without arguments. |
| [tools/observe_owned_lobby_filter.py](../tools/observe_owned_lobby_filter.py) | Bounded read-only owned client cache/filter observer; no native UI calls. |
| [tools/observe_owned_lobby_rows.py](../tools/observe_owned_lobby_rows.py) | Bounded read-only observers for the explicitly owned C legacy QA client. |
| [tools/observe_owned_main_list_transition.py](../tools/observe_owned_main_list_transition.py) | Bounded read-only native flow observer in an explicitly owned QA client. |
| [tools/observe_owned_selector_state.py](../tools/observe_owned_selector_state.py) | One read-only selector/roster snapshot of an explicitly owned QA PID. |
| [tools/offsite_backup_windows.py](../tools/offsite_backup_windows.py) | Private platform recovery capture encrypted with Windows CurrentUser DPAPI. |
| [tools/onboard_portal_admin.py](../tools/onboard_portal_admin.py) | Link an explicitly authorized administrator through the public secure API. |
| [tools/operate_shared_mines_maintenance.py](../tools/operate_shared_mines_maintenance.py) | Explicit operator entry point for the reviewed, temporary hosted QA lease. |
| [tools/package_portal_standalone.py](../tools/package_portal_standalone.py) | Package a portable Next standalone with its installed runtime dependencies. |
| [tools/pin_original_names_preparation_dependencies.py](../tools/pin_original_names_preparation_dependencies.py) | Additional provenance for the imported read-only protected-runtime list. |
| [tools/player_trade_graphical_qa.py](../tools/player_trade_graphical_qa.py) | Owned native GUI barter QA via the exact published launcher and real TLS. |
| [tools/player_trade_qa_cleanup.py](../tools/player_trade_qa_cleanup.py) | Remove receipts only for two parties owned by a disposable QA run. |
| [tools/prepare_achievement_city_fix.py](../tools/prepare_achievement_city_fix.py) | Capture the live code and freeze a scoped achievement delivery fix. |
| [tools/prepare_admission_capacity_deploy.py](../tools/prepare_admission_capacity_deploy.py) | Inspect actual remote sources and prepare a code-only guarded update. |
| [tools/prepare_admission_capacity_localization.py](../tools/prepare_admission_capacity_localization.py) | Inspect actual remote sources and prepare a code-only guarded update. |
| [tools/prepare_arena_boundaries_deploy.py](../tools/prepare_arena_boundaries_deploy.py) | Offline .2 -> .3 boundary packaging; no hosted writes or player data. |
| [tools/prepare_arena_fog_assets.py](../tools/prepare_arena_fog_assets.py) | Set a constant native foreground tint; retain every pixel and map byte. |
| [tools/prepare_arena_fog_deploy.py](../tools/prepare_arena_fog_deploy.py) | Prepare an offline .1 -> .2 client-only RGB tint release; never uploads. |
| [tools/prepare_arena_gears_deploy.py](../tools/prepare_arena_gears_deploy.py) | Inspect live sources and prepare a guarded code-only cities update. |
| [tools/prepare_arena_surroundings_deploy.py](../tools/prepare_arena_surroundings_deploy.py) | Build reviewed new-only assets and the five-file server overlay; no upload. |
| [tools/prepare_backup_tools_deploy.py](../tools/prepare_backup_tools_deploy.py) | Build a reviewable Stage3 backup-tools package locally; never contacts a host. |
| [tools/prepare_battle_item_catalog.py](../tools/prepare_battle_item_catalog.py) | Merge the reviewed item overlay into exact published XML and server catalogs. |
| [tools/prepare_battle_recovery_deploy.py](../tools/prepare_battle_recovery_deploy.py) | Inspect actual remote sources and prepare a code-only guarded update. |
| [tools/prepare_battle_safety_deploy.py](../tools/prepare_battle_safety_deploy.py) | Inspect actual remote sources and prepare a code-only guarded update. |
| [tools/prepare_battle_screen_fixes_patch.py](../tools/prepare_battle_screen_fixes_patch.py) | Package only the screenshot fixes, checked against the inspected hosted baseline. |
| [tools/prepare_battle_turn_deploy.py](../tools/prepare_battle_turn_deploy.py) | Inspect live sources and prepare a guarded code-only cities update. |
| [tools/prepare_bot_credit_rewards_patch.py](../tools/prepare_bot_credit_rewards_patch.py) | Package only the bot finishing, checked against the inspected hosted baseline. |
| [tools/prepare_bot_finishing_patch.py](../tools/prepare_bot_finishing_patch.py) | Package only the bot finishing, checked against the inspected hosted baseline. |
| [tools/prepare_chat_echo_deploy.py](../tools/prepare_chat_echo_deploy.py) | Build a one-file patch against the inspected live chat-presence source. |
| [tools/prepare_cities_deploy.py](../tools/prepare_cities_deploy.py) | Inspect live sources and prepare a guarded code-only cities update. |
| [tools/prepare_city_api_runtime.py](../tools/prepare_city_api_runtime.py) | Provide only the existing bank key to the in-process city API, backed up. |
| [tools/prepare_city_interface_release.py](../tools/prepare_city_interface_release.py) | Freeze four reviewed city files over the published multiplayer runtime. |
| [tools/prepare_city_inventory_fix.py](../tools/prepare_city_inventory_fix.py) | Freeze the observed fresh-city item decoder fix over the actual public tree. |
| [tools/prepare_city_portal_links.py](../tools/prepare_city_portal_links.py) | Insert the reviewed city page link without rebuilding unrelated content. |
| [tools/prepare_clan_portal_runtime.py](../tools/prepare_clan_portal_runtime.py) | Back up and permit only the new Next cache; preserve live game identity. |
| [tools/prepare_clans_deploy.py](../tools/prepare_clans_deploy.py) | Inspect live sources and prepare a guarded code-only clans update. |
| [tools/prepare_contracts_city_local.py](../tools/prepare_contracts_city_local.py) | Install/roll back the reviewed city skin in the two owned loopback clients. |
| [tools/prepare_contracts_local.py](../tools/prepare_contracts_local.py) | Prepare an isolated loopback test kit from an already verified local QA copy. |
| [tools/prepare_durability_patch.py](../tools/prepare_durability_patch.py) | См. код и вызывающие модули. |
| [tools/prepare_encounters_deploy.py](../tools/prepare_encounters_deploy.py) | Prepare guarded server and client overlays against the actual published state. |
| [tools/prepare_forest_deploy.py](../tools/prepare_forest_deploy.py) | Guarded runtime/client overlay against this turn's actual hosted baseline. |
| [tools/prepare_game_tls_deploy.py](../tools/prepare_game_tls_deploy.py) | Read the actual VPS baseline and package only the authorized game TLS files. |
| [tools/prepare_game_tls_native_match.py](../tools/prepare_game_tls_native_match.py) | Retain one owned two-human match for subsequent real native TLS validation. |
| [tools/prepare_generated_avatars.py](../tools/prepare_generated_avatars.py) | Inspect the authoritative avatar release without touching hosted saves. |
| [tools/prepare_github_handoff.py](../tools/prepare_github_handoff.py) | Export an explicit source-only snapshot; never copy production state or secrets. |
| [tools/prepare_graphical_arena_boundaries_match.py](../tools/prepare_graphical_arena_boundaries_match.py) | Use the frozen owned hosted stager with strict published .3 boundaries. |
| [tools/prepare_graphical_arena_fog_match.py](../tools/prepare_graphical_arena_fog_match.py) | Use the established owned public matchmaking harness for the fog release. |
| [tools/prepare_graphical_arena_match.py](../tools/prepare_graphical_arena_match.py) | Prepare or explicitly retire one owned hosted graphical QA match. |
| [tools/prepare_healing_probe.py](../tools/prepare_healing_probe.py) | Create a NEW isolated dog1 database. Never modifies the player's database. |
| [tools/prepare_hosted_graphical_qa.py](../tools/prepare_hosted_graphical_qa.py) | Prepare two owned QA game copies solely from the current public manifest. |
| [tools/prepare_hosted_turn_order_probe.py](../tools/prepare_hosted_turn_order_probe.py) | Reuse the fresh-account TCP onboarding setup for a bounded order check. |
| [tools/prepare_interface_portal_runtime.py](../tools/prepare_interface_portal_runtime.py) | Permit the reviewed interface cache after validating a fresh site backup. |
| [tools/prepare_launcher_014_package.py](../tools/prepare_launcher_014_package.py) | Prepare reviewable 0.1.4 publication invocations locally; no remote action. |
| [tools/prepare_launcher_publication.py](../tools/prepare_launcher_publication.py) | Inspect and optionally back up the hosted launcher publication before review. |
| [tools/prepare_legacy_lobby_negative_fixture.py](../tools/prepare_legacy_lobby_negative_fixture.py) | Adjust only owned QA account D's level/XP for the actual lobby GUI check. |
| [tools/prepare_miners_town_shop_protocol.py](../tools/prepare_miners_town_shop_protocol.py) | Apply one catalogue rejection boundary to the exact inspected host runtime. |
| [tools/prepare_native_lobby_live_projection_deployment.py](../tools/prepare_native_lobby_live_projection_deployment.py) | Prepare exact live BA projection and original Names; read-only remote inspection. |
| [tools/prepare_native_lobby_original_names_deployment.py](../tools/prepare_native_lobby_original_names_deployment.py) | Prepare only the exact reviewed two-file update; read-only hosted inspection. |
| [tools/prepare_new_player_qa.py](../tools/prepare_new_player_qa.py) | Prepare private credentials and a remote backup; never create game accounts. |
| [tools/prepare_owned_d_dual_negative_fixture.py](../tools/prepare_owned_d_dual_negative_fixture.py) | Owned D dual-fighter QA fixture; inspect is read only, prepare/restore explicit. |
| [tools/prepare_owned_d_dual_negative_fixture_v2.py](../tools/prepare_owned_d_dual_negative_fixture_v2.py) | Owned D dual-fighter QA fixture; inspect is read only, prepare/restore explicit. |
| [tools/prepare_player_statistics_deploy.py](../tools/prepare_player_statistics_deploy.py) | Inspect actual remote sources and prepare a code-only guarded update. |
| [tools/prepare_player_trade.py](../tools/prepare_player_trade.py) | Build a scoped candidate from the inspected hosted runtime, never old locals. |
| [tools/prepare_ranked_deploy.py](../tools/prepare_ranked_deploy.py) | Inspect live sources and prepare a guarded code-only ranked update. |
| [tools/prepare_rating_completion_candidate.py](../tools/prepare_rating_completion_candidate.py) | Prepare only owned rating scopes from immutable published public sources. |
| [tools/prepare_ratings_portal_candidate.py](../tools/prepare_ratings_portal_candidate.py) | Prepare only the two scoped published HTTP adapters for ratings review. |
| [tools/prepare_reservation_crate_alpha.py](../tools/prepare_reservation_crate_alpha.py) | Restore native BMP serialization without changing generated texture pixels. |
| [tools/prepare_reservation_deploy.py](../tools/prepare_reservation_deploy.py) | Guarded runtime/client overlay against this turn's actual hosted baseline. |
| [tools/prepare_shop_completion_release.py](../tools/prepare_shop_completion_release.py) | Freeze reviewed shops over the published city runtime, excluding local contracts. |
| [tools/prepare_site_backups_remote.py](../tools/prepare_site_backups_remote.py) | Save hosted databases and previous code/config before a portal/backup update. |
| [tools/prepare_stage34_portal_integration.py](../tools/prepare_stage34_portal_integration.py) | Copy frozen new portal files and emit two separately reviewed patch hunks. |
| [tools/prepare_stage9_interfaces.py](../tools/prepare_stage9_interfaces.py) | Freeze reviewed interface changes over the actual public server snapshot. |
| [tools/prepare_stage9_interfaces_revision2.py](../tools/prepare_stage9_interfaces_revision2.py) | Retain revision1 evidence; add a scoped passive market-window fix. |
| [tools/prepare_steam_package.py](../tools/prepare_steam_package.py) | Build an isolated SteamPipe Windows package from the verified public client. |
| [tools/prepare_tactical_bots_patch.py](../tools/prepare_tactical_bots_patch.py) | Package only the bot patch, checked against the inspected hosted baseline. |
| [tools/prepare_treatment_patch.py](../tools/prepare_treatment_patch.py) | Package treatment and the already-reviewed pending turn-order fix. |
| [tools/prepare_turn_order_patch.py](../tools/prepare_turn_order_patch.py) | Package the reviewed order-packet changes; no player database included. |
| [tools/prepare_tutorial_creation_patch.py](../tools/prepare_tutorial_creation_patch.py) | Generate a reviewable creation diff without changing CharacterStore. |
| [tools/prepare_ui_scale_battle_qa.py](../tools/prepare_ui_scale_battle_qa.py) | Reuse the owned public two-account arena fixture for UI scale QA. |
| [tools/prepare_warehouse_services_release.py](../tools/prepare_warehouse_services_release.py) | Freeze warehouses/services over reviewed shops; preserve unrelated local work. |
| [tools/prepare_world_completion_catalog.py](../tools/prepare_world_completion_catalog.py) | Prepare the bounded world catalogue from observed server/client sources. |
| [tools/prepare_world_runtime.py](../tools/prepare_world_runtime.py) | Freeze reviewed world sources while retaining explicit public-only overrides. |
| [tools/probe_item_fixture.py](../tools/probe_item_fixture.py) | Install diagnostic XML, recovering verified leftovers from interrupted runs. |
| [tools/probe_ui_modernization_startup_owned.py](../tools/probe_ui_modernization_startup_owned.py) | Read-only diagnosis of an already running, exact marker-owned QA client. |
| [tools/probe_windowed.py](../tools/probe_windowed.py) | Run an owned diagnostic client with temporary windowed rendering settings. |
| [tools/provision_user_test_accounts.py](../tools/provision_user_test_accounts.py) | Inspect/provision the user-requested Test1/Test2 hosted fixtures. |
| [tools/publish_arena_boundaries.py](../tools/publish_arena_boundaries.py) | Guarded client-only .3 boundary publication; --execute is required. |
| [tools/publish_arena_fog.py](../tools/publish_arena_fog.py) | Publish the reviewed client-only .1 -> .2 tint patch only with --execute. |
| [tools/publish_arena_surroundings.py](../tools/publish_arena_surroundings.py) | Explicitly upload the prepared release, verify a hosted candidate and deploy. |
| [tools/publish_battle_icon_centering_remote.py](../tools/publish_battle_icon_centering_remote.py) | Scoped .2 -> .3 publication of the reviewed battle glyph centering fix. |
| [tools/publish_battle_ui_hd_remote.py](../tools/publish_battle_ui_hd_remote.py) | Scoped .13 -> 2026.10.10.1 client UI quality/tooltip publication. |
| [tools/publish_english_localization.py](../tools/publish_english_localization.py) | Publish only reviewed localization code/resources against the actual host. |
| [tools/publish_equipment_textures.py](../tools/publish_equipment_textures.py) | Publish the verified asset-only release and verify every public HTTPS blob. |
| [tools/publish_game_tls_download_metadata.py](../tools/publish_game_tls_download_metadata.py) | Root-only scoped portal metadata publication after launcher TLS acceptance. |
| [tools/publish_gameplay_equipment_client.py](../tools/publish_gameplay_equipment_client.py) | Publish the verified equipment DLL with fresh backups and HTTPS proof. |
| [tools/publish_gameplay_items_client.py](../tools/publish_gameplay_items_client.py) | Publish the bounded item adapter and reviewed XML against exact live blobs. |
| [tools/publish_gameplay_nvg_client.py](../tools/publish_gameplay_nvg_client.py) | Review/publish the exact .5 -> .6 F9 NVG client; no DB or service restart. |
| [tools/publish_gameplay_sc_client.py](../tools/publish_gameplay_sc_client.py) | Build/review the exact SC F8 client, then explicitly publish only silver.dll. |
| [tools/publish_gameplay_xml_client.py](../tools/publish_gameplay_xml_client.py) | Publish a bounded XML-only catalogue release, preserving other client blobs. |
| [tools/publish_global_map_remote.py](../tools/publish_global_map_remote.py) | Scoped .2026.10.10.4 -> .5 publication of original global-map PNGs. |
| [tools/publish_launcher_014_remote.py](../tools/publish_launcher_014_remote.py) | Root-only, guarded launcher 0.1.4 publication; no game code or DB restore. |
| [tools/publish_launcher_update_remote.py](../tools/publish_launcher_update_remote.py) | Root-only launcher self-update publication from an explicitly pinned baseline. |
| [tools/publish_legacy_lobbies_client.py](../tools/publish_legacy_lobbies_client.py) | Publish the bounded native lobby and texture fix using the reviewed transaction. |
| [tools/publish_legacy_navigation_browse_ascii_client.py](../tools/publish_legacy_navigation_browse_ascii_client.py) | Scoped .2 -> .3 legacy arena navigation, occupied-state colours, thirteen HUD textures and help. |
| [tools/publish_legacy_navigation_busy_ascii_client.py](../tools/publish_legacy_navigation_busy_ascii_client.py) | Scoped .2 -> .3 legacy arena navigation, occupied-state colours, thirteen HUD textures and help. |
| [tools/publish_legacy_navigation_busy_client.py](../tools/publish_legacy_navigation_busy_client.py) | Scoped .2 -> .3 legacy arena navigation, occupied-state colours, thirteen HUD textures and help. |
| [tools/publish_legacy_navigation_client.py](../tools/publish_legacy_navigation_client.py) | Scoped .2 -> .3 legacy arena navigation and thirteen main-HUD textures. |
| [tools/publish_legacy_navigation_empty_ascii_client.py](../tools/publish_legacy_navigation_empty_ascii_client.py) | Scoped .2 -> .3 legacy arena navigation, occupied-state colours, thirteen HUD textures and help. |
| [tools/publish_legacy_navigation_help_client.py](../tools/publish_legacy_navigation_help_client.py) | Scoped .2 -> .3 legacy arena navigation, thirteen main-HUD textures and one help line. |
| [tools/publish_legacy_project_agreement_client.py](../tools/publish_legacy_project_agreement_client.py) | One-file .3 -> .4 publication of the TI-REBORN native user agreement. |
| [tools/publish_legacy_status_client.py](../tools/publish_legacy_status_client.py) | Scoped 2026.10.11.1 -> .2 Silver and thirteen native texture publisher. |
| [tools/publish_mine_drill_ui_remote.py](../tools/publish_mine_drill_ui_remote.py) | Scoped .1 -> .2 mine hover and native icon rendering hotfix publication. |
| [tools/publish_mine_path_entry_remote.py](../tools/publish_mine_path_entry_remote.py) | Scoped .3 -> .4 completed-scene native path cache hotfix publication. |
| [tools/publish_reservation_textures.py](../tools/publish_reservation_textures.py) | Upload the reviewed client overlay, verify the hosted candidate, then deploy. |
| [tools/publish_screen_settings_remote.py](../tools/publish_screen_settings_remote.py) | Inspect or publish the reviewed silver.dll screen-settings client update. |
| [tools/publish_ui_hd_assets_remote.py](../tools/publish_ui_hd_assets_remote.py) | Scoped .12 -> .13 publication of reviewed A icons / Roboto Condensed assets. |
| [tools/publish_ui_modernization_remote.py](../tools/publish_ui_modernization_remote.py) | Scoped .11 -> .12 client publisher for reviewed UI/portrait native patches. |
| [tools/publish_world_completion_client.py](../tools/publish_world_completion_client.py) | Prepare, publish or verify the bounded world zones XML client release. |
| [tools/re_range.py](../tools/re_range.py) | См. код и вызывающие модули. |
| [tools/read_tile_doors_extended_native.py](../tools/read_tile_doors_extended_native.py) | Extract door cells using the installed ti.exe TILE v2/v4/v5 record readers. |
| [tools/read_tile_doors_native.py](../tools/read_tile_doors_native.py) | Extract door cells using the installed ti.exe TILE v4/v5 record readers. |
| [tools/record_stage9_gui_acceptance.py](../tools/record_stage9_gui_acceptance.py) | Record observed GUI checks without upgrading partial acceptance to complete. |
| [tools/recover_stage4_qa_credentials.py](../tools/recover_stage4_qa_credentials.py) | Recover only the empty owned QA pair from the recorded local ACL failure. |
| [tools/refresh_clan_gateway.py](../tools/refresh_clan_gateway.py) | Load the deployed crest API, retaining protected keys and game identity. |
| [tools/remove_hosted_unity_client.py](../tools/remove_hosted_unity_client.py) | Remove only the user-authorized public Unity namespace; preserve legacy data. |
| [tools/remove_user_test_accounts.py](../tools/remove_user_test_accounts.py) | Remove only the Test1/Test2 accounts created in the current user task. |
| [tools/repack_battle_glyphs_centered.py](../tools/repack_battle_glyphs_centered.py) | Technically register the reviewed battle artwork into native atlas cells. |
| [tools/report_item_weights.py](../tools/report_item_weights.py) | Write an auditable list of every current item's original unit mass. |
| [tools/report_rating_completion.py](../tools/report_rating_completion.py) | Record reviewable rating evidence and a strict read-only UI contract. |
| [tools/report_ratings_portal.py](../tools/report_ratings_portal.py) | Tie the frozen ratings portal delivery to exact focused public test sources. |
| [tools/research_clan_native.py](../tools/research_clan_native.py) | Read-only original clan protocol investigation. |
| [tools/research_loot.py](../tools/research_loot.py) | Read-only disassembly helper for the original loot protocol. |
| [tools/research_screen_native.py](../tools/research_screen_native.py) | Read-only disassembly of the pinned TI rendering and screen settings paths. |
| [tools/reservation_texture_assets.py](../tools/reservation_texture_assets.py) | Published source inventory and isolated Reservation material replacements. |
| [tools/reservation_texture_export.py](../tools/reservation_texture_export.py) | Technical UV/codec export of AI art; keep native masks and geometry. |
| [tools/reservation_texture_review.py](../tools/reservation_texture_review.py) | Contact sheets of decoded source/export assets for visual quality checks. |
| [tools/restart_gateway_for_scoped_release.py](../tools/restart_gateway_for_scoped_release.py) | Activate an already deployed gateway revision with private config backup. |
| [tools/resume_user_agreement_portal.py](../tools/resume_user_agreement_portal.py) | Resume the already extracted, pinned legal-page release without uploading it. |
| [tools/retire_game_tls_native_match.py](../tools/retire_game_tls_native_match.py) | Retire only the expected owned QA match through ordinary verified TLS Leave. |
| [tools/review_ui_hd_font_filename_abi.py](../tools/review_ui_hd_font_filename_abi.py) | Inspect real embedded font filenames through the pinned TI basename scanner. |
| [tools/review_ui_hd_package_static.py](../tools/review_ui_hd_package_static.py) | Independent static review of the exact selected HD package and native hooks. |
| [tools/revise_stage34_portal_integration.py](../tools/revise_stage34_portal_integration.py) | Add only the reviewed fund UI strings; retain the earlier integration proof. |
| [tools/run_full_tests.py](../tools/run_full_tests.py) | Whole legacy suite; separates environment gaps and documented known failures from real ones. |
| [tools/run_hosted_surroundings_qa.py](../tools/run_hosted_surroundings_qa.py) | Bounded public multiplayer diagnostics using an existing owned QA fixture. |
| [tools/run_launcher_update_publication.py](../tools/run_launcher_update_publication.py) | Stage and publish a tested launcher using a fresh hosted backup, via SSH. |
| [tools/run_legacy_graphical_qa.py](../tools/run_legacy_graphical_qa.py) | Own real 0.1.6 graphical client and genuine hosted TLS authentication. |
| [tools/run_native_lobby_live_projection_tests.py](../tools/run_native_lobby_live_projection_tests.py) | Prior111 checks plus live city projection over actual TCP; isolated runtime only. |
| [tools/run_native_lobby_original_names_tests.py](../tools/run_native_lobby_original_names_tests.py) | Execute exactly the prior111 suite against the isolated original-name variant. |
| [tools/run_offsite_backup_job.py](../tools/run_offsite_backup_job.py) | Hidden scheduled-job wrapper with a credential-free local status record. |
| [tools/run_reservation.py](../tools/run_reservation.py) | Reproduce the verified Reservation bootstrap against the original TI client. |
| [tools/run_reviewed_launcher_014_publication.py](../tools/run_reviewed_launcher_014_publication.py) | Execute the explicitly reviewed one-time 0.1.4 publication package. |
| [tools/run_shared_mines_tests.py](../tools/run_shared_mines_tests.py) | Capture the full suite against the shared-mines candidate without replacing prior evidence. |
| [tools/run_stage4_tests.py](../tools/run_stage4_tests.py) | Capture the full backend suite with source hashes and a bounded runtime. |
| [tools/save_gameplay_followup_handoff.py](../tools/save_gameplay_followup_handoff.py) | Save the user-requested stopping point without changing game state. |
| [tools/seal_evidence.py](../tools/seal_evidence.py) | Record reproducible hashes for local evidence; does not alter source artifacts. |
| [tools/set_requested_account_balances_levels.py](../tools/set_requested_account_balances_levels.py) | Scoped hosted update requested for admin/Sasamasa and player_two. |
| [tools/shared_mines_maintenance.py](../tools/shared_mines_maintenance.py) | Fail-closed, lease-owned ingress isolation for three fresh mining QA accounts. |
| [tools/shared_mines_route.py](../tools/shared_mines_route.py) | Pure route planning for the three-owned-account mining verifier. |
| [tools/shooting_range_scene.py](../tools/shooting_range_scene.py) | Original 38x38 shootingrange resource and mob10 wooden targets. |
| [tools/start_hosted_graphical_qa.py](../tools/start_hosted_graphical_qa.py) | Start two dedicated clients with ownership-checked private QA credentials. |
| [tools/summarize_public_runtime_regression.py](../tools/summarize_public_runtime_regression.py) | Combine immutable bounded public runs without relabelling failures as PASS. |
| [tools/survival_scene.py](../tools/survival_scene.py) | Prepare a local training opponent and full selected squad atomically. |
| [tools/test_native_lobby_departure_tcp.py](../tools/test_native_lobby_departure_tcp.py) | Two-account Team/Wall departure over actual localhost TCP/native framing. |
| [tools/test_native_lobby_live_projection.py](../tools/test_native_lobby_live_projection.py) | Actual three TCP peers, native cipher/frames and changed BA02/BA06 city lists. |
| [tools/test_portal_isolated_postgres.py](../tools/test_portal_isolated_postgres.py) | Run portal tests using an owned disposable PostgreSQL database via SSH. |
| [tools/test_publish_ui_modernization_remote.py](../tools/test_publish_ui_modernization_remote.py) | Guard tests with isolated native fixtures and a temporary hosted filesystem. |
| [tools/test_ui_hd_assets_publication.py](../tools/test_ui_hd_assets_publication.py) | Fault-injected multi-resource publication/verification in owned local fixtures. |
| [tools/test_verify_ui_modernization_publication.py](../tools/test_verify_ui_modernization_publication.py) | Exercise the independent checker against synthetic local hosted backups. |
| [tools/trace_battle_soldier_native.py](../tools/trace_battle_soldier_native.py) | Trace original BattleSoldierAdd3B read phase with explicit UI/model/allocation stubs. |
| [tools/trace_door_session.py](../tools/trace_door_session.py) | Read-only trace of native movement/door transitions in an existing client. |
| [tools/trace_pet_info_native.py](../tools/trace_pet_info_native.py) | Trace original PetInfo66 branches with explicit UI/model/allocation stubs. |
| [tools/trace_portrait_input_owned.py](../tools/trace_portrait_input_owned.py) | Observe real mouse dispatch in an exact owned QA client; never send input. |
| [tools/trace_shop_live.py](../tools/trace_shop_live.py) | Observe native shop/warehouse transitions without changing client data. |
| [tools/ui_scale_battle_assets.py](../tools/ui_scale_battle_assets.py) | Read-only inherited .3 arena proof bound to the exact public .11 manifest. |
| [tools/ui_scale_battle_preservation.py](../tools/ui_scale_battle_preservation.py) | Current-epoch preservation for the exact retained UI battle QA pair. |
| [tools/validate_achievement_city_fix.py](../tools/validate_achievement_city_fix.py) | Verify the captured production revision with disposable databases and TCP peers. |
| [tools/validate_gameplay_modes.py](../tools/validate_gameplay_modes.py) | Validate frozen multiplayer sources locally and in a disposable hosted tree. |
| [tools/verify_ability_cast_native.py](../tools/verify_ability_cast_native.py) | Execute original81 writer with real integer writers; transport isolated. |
| [tools/verify_ability_requests_native.py](../tools/verify_ability_requests_native.py) | Execute original 8F/90 writers; isolate transport acquisition/flush only. |
| [tools/verify_ability_status_native.py](../tools/verify_ability_status_native.py) | Execute original7F/01 serializer and8c0790 model consumer. |
| [tools/verify_achievements_native.py](../tools/verify_achievements_native.py) | Run original B502/B503 readers, stubbing allocation, strings and GUI only. |
| [tools/verify_action_points_native.py](../tools/verify_action_points_native.py) | Original4E serializer and status10 branch writing actor+6004. |
| [tools/verify_actual_arena_entry_native.py](../tools/verify_actual_arena_entry_native.py) | Actual85A0F2 Arena mode argument -> selector state -> original BA01 browse. |
| [tools/verify_admission_capacity_remote.py](../tools/verify_admission_capacity_remote.py) | Exercise deployed sources on temporary SQLite and isolated loopback listeners. |
| [tools/verify_appearance_native.py](../tools/verify_appearance_native.py) | Execute original customization92 writer and appearance reader; transport stubbed. |
| [tools/verify_arena_browsing_visible_native.py](../tools/verify_arena_browsing_visible_native.py) | Real x86 selector, BA02 parser/colour path, full lobby draw and numeric formatter. |
| [tools/verify_arena_browsing_window_flow_native.py](../tools/verify_arena_browsing_window_flow_native.py) | Actual selector callback -> registry Show -> OnShow -> category event -> BA01. |
| [tools/verify_arena_callback_queue.py](../tools/verify_arena_callback_queue.py) | Execute original ti.exe callback71cc6c through queuing of copied packet bytes. |
| [tools/verify_arena_create_binding.py](../tools/verify_arena_create_binding.py) | Verify Create button interface binding and execute its native callback chain. |
| [tools/verify_arena_create_form_native.py](../tools/verify_arena_create_form_native.py) | Execute original confirmation85d658 through C8/2B numeric serialization. |
| [tools/verify_arena_create_request_native.py](../tools/verify_arena_create_request_native.py) | Execute create battle a0a6f4, typed setters/serializer and real numeric writers. |
| [tools/verify_arena_empty_roster_navigation_native.py](../tools/verify_arena_empty_roster_navigation_native.py) | Real x86 selector, BA02 parser/colour path, full lobby draw and numeric formatter. |
| [tools/verify_arena_gears_native.py](../tools/verify_arena_gears_native.py) | Original C6 dispatcher, numeric catalogue reader and city loading gate. |
| [tools/verify_arena_gears_remote.py](../tools/verify_arena_gears_remote.py) | Run focused tests in an isolated copy of the actual hosted code. |
| [tools/verify_arena_lobby_navigation_native.py](../tools/verify_arena_lobby_navigation_native.py) | Real x86 selector, BA02 parser/colour path, full lobby draw and numeric formatter. |
| [tools/verify_arena_lobby_search_status_native.py](../tools/verify_arena_lobby_search_status_native.py) | Real x86 selector, BA02 parser/colour path, full lobby draw and numeric formatter. |
| [tools/verify_arena_members_native.py](../tools/verify_arena_members_native.py) | Original BA0B dispatcher/member consumer through return; strings/chat/UI isolated. |
| [tools/verify_arena_mode_ranges_native.py](../tools/verify_arena_mode_ranges_native.py) | Original85decc arena range callback; UI track access/setters isolated. |
| [tools/verify_arena_ready_native.py](../tools/verify_arena_ready_native.py) | Original BA08 consumer: matching search/character only, boolean state. |
| [tools/verify_arena_requests_native.py](../tools/verify_arena_requests_native.py) | Run original Arena request builders and real byte/u32 writers; stub transport/UI. |
| [tools/verify_arena_room_native.py](../tools/verify_arena_room_native.py) | Execute Arena BA/02 dispatch and numeric room parser; isolate allocation/strings/UI. |
| [tools/verify_arena_roster_count_native.py](../tools/verify_arena_roster_count_native.py) | Verify BA03 caller uses arena category and count of pets with nonzero state. |
| [tools/verify_arena_surroundings_candidate_remote.py](../tools/verify_arena_surroundings_candidate_remote.py) | Run focused tests in a copy of hosted code; no live database/service writes. |
| [tools/verify_arena_surroundings_native.py](../tools/verify_arena_surroundings_native.py) | Reproducible original-ti.exe probes for decorative surrounding resources. |
| [tools/verify_armor_display_native.py](../tools/verify_armor_display_native.py) | Original 66/3B armor reads and 4E attribute9 serializer/model write. |
| [tools/verify_assault_badge_native.py](../tools/verify_assault_badge_native.py) | Execute original 83 reader -> clan row draw -> weekly badge sprite choice. |
| [tools/verify_asset_count_native.py](../tools/verify_asset_count_native.py) | Execute original AssetCount reader and wallet consumer with explicit UI stubs. |
| [tools/verify_attack_native.py](../tools/verify_attack_native.py) | Execute original49 request and4B result writers against Python encoders. |
| [tools/verify_auth2_native.py](../tools/verify_auth2_native.py) | Original0D dispatcher/parser; logging and UI/string helpers stubbed. |
| [tools/verify_auth_native.py](../tools/verify_auth_native.py) | Execute original TIO x86 dispatcher/parser in Unicorn, with explicit UI stubs. |
| [tools/verify_avatar_types_native.py](../tools/verify_avatar_types_native.py) | Execute the released-chain avatar assignment and original catalog/image readers. |
| [tools/verify_avatars_native.py](../tools/verify_avatars_native.py) | Execute the released-chain avatar assignment and original catalog/image readers. |
| [tools/verify_bank_operations_hosted.py](../tools/verify_bank_operations_hosted.py) | Two excluded hosted TLS accounts check bank operations after installation. |
| [tools/verify_bank_trade_release_health.py](../tools/verify_bank_trade_release_health.py) | Read-only final production checks after both hosted acceptance scenarios. |
| [tools/verify_battle_core_native.py](../tools/verify_battle_core_native.py) | Check original x86 chat readers and attack writers, with documented UI stubs. |
| [tools/verify_battle_core_state_remote.py](../tools/verify_battle_core_state_remote.py) | Read-only hosted verification against the pre-update SQLite backup. |
| [tools/verify_battle_doors_native.py](../tools/verify_battle_doors_native.py) | Original3E writer,3F consumer, door animation/frame/collision and path lookup. |
| [tools/verify_battle_equipment_native.py](../tools/verify_battle_equipment_native.py) | Original3B equipment reads and98f978 slot dispatch; managed copy isolated. |
| [tools/verify_battle_exchange_native.py](../tools/verify_battle_exchange_native.py) | Execute original6E writer plus released opening/AP/predicate hooks in Unicorn. |
| [tools/verify_battle_glyph_centering_native.py](../tools/verify_battle_glyph_centering_native.py) | Prove atlas-only centering against the unchanged .2 native renderer. |
| [tools/verify_battle_ground_native.py](../tools/verify_battle_ground_native.py) | Original BattleGround35 reader: numeric reads/loops and grid writes execute. |
| [tools/verify_battle_ground_scene_native.py](../tools/verify_battle_ground_scene_native.py) | ti.exe717e1c ground numeric reads and both scene-grid layers. |
| [tools/verify_battle_item_catalog_native.py](../tools/verify_battle_item_catalog_native.py) | Bounded original XML metadata loader proof for the approved item overlay. |
| [tools/verify_battle_item_client_native.py](../tools/verify_battle_item_client_native.py) | Execute candidate item GUI guards,33→target49, F7 parser and draw callback. |
| [tools/verify_battle_item_native.py](../tools/verify_battle_item_native.py) | Execute native4E sight writer/consumer and33/49/4B item envelopes. |
| [tools/verify_battle_loaded_native.py](../tools/verify_battle_loaded_native.py) | Original ti.exe load completion gate36 and silver.dll member-loaded37. |
| [tools/verify_battle_loot_client_native.py](../tools/verify_battle_loot_client_native.py) | Execute original transfer predicate with the release hook and catalog checks. |
| [tools/verify_battle_loot_native.py](../tools/verify_battle_loot_native.py) | Original47 serializer/consumer and46/40 client request writers. |
| [tools/verify_battle_member_consumer_native.py](../tools/verify_battle_member_consumer_native.py) | Execute original a0a29c slot selection; record conversion and UI are isolated. |
| [tools/verify_battle_member_list_native.py](../tools/verify_battle_member_list_native.py) | Original BattleMemberList25 numeric reader, records without nested arrays. |
| [tools/verify_battle_member_nested_native.py](../tools/verify_battle_member_nested_native.py) | Original BattleMemberList25 numeric reader, records with both nested arrays and group2 word children. |
| [tools/verify_battle_member_rtti.py](../tools/verify_battle_member_rtti.py) | Pin group1 RTTI field offsets/getter addresses to original numeric readers. |
| [tools/verify_battle_move_native.py](../tools/verify_battle_move_native.py) | Original ti.exe6dc600 reader/path loop and final coordinate writes. |
| [tools/verify_battle_over_native.py](../tools/verify_battle_over_native.py) | Execute original4C ordinary summary reader95e55e..95ea7d. |
| [tools/verify_battle_position_gate_native.py](../tools/verify_battle_position_gate_native.py) | Execute original95d39c and its real x87 distance helper; selection isolated. |
| [tools/verify_battle_position_request_native.py](../tools/verify_battle_position_request_native.py) | Original95e114 actor/coordinate46 writer; disabled gate, transport/UI isolated. |
| [tools/verify_battle_recovery_remote.py](../tools/verify_battle_recovery_remote.py) | Candidate/deployed crash checks on the VPS, isolated from hosted players. |
| [tools/verify_battle_remove_native.py](../tools/verify_battle_remove_native.py) | Execute original43 reader and model removal writes, stopping before UI notification. |
| [tools/verify_battle_rental_restore_native.py](../tools/verify_battle_rental_restore_native.py) | Original3B default gear vs original30 rental/upgrade readers in Unicorn. |
| [tools/verify_battle_safety_remote.py](../tools/verify_battle_safety_remote.py) | Exercise deployed sources on temporary SQLite and isolated loopback listeners. |
| [tools/verify_battle_screen_fixes_health_remote.py](../tools/verify_battle_screen_fixes_health_remote.py) | Read-only final health/source/save comparison. Run on the hosted server. |
| [tools/verify_battle_screen_fixes_hosted.py](../tools/verify_battle_screen_fixes_hosted.py) | Screenshot regressions and multiplayer bot gameplay over hosted TLS. |
| [tools/verify_battle_settings_labels.py](../tools/verify_battle_settings_labels.py) | Verify original room-info label/field bindings against the pinned client. |
| [tools/verify_battle_settings_native.py](../tools/verify_battle_settings_native.py) | Execute BattleSettings numeric reader; isolate managed values/strings/UI. |
| [tools/verify_battle_soldier_native.py](../tools/verify_battle_soldier_native.py) | Replay encoded BattleSoldier3B through original read phase with marker values. |
| [tools/verify_battle_target_request_native.py](../tools/verify_battle_target_request_native.py) | Execute original9595f0 ->6585cc C8/3D builder with real field writers. |
| [tools/verify_battle_tooltip_scale_native.py](../tools/verify_battle_tooltip_scale_native.py) | Execute the actual battle cursor balloon and existing GPU scale x86. |
| [tools/verify_battle_turn_regressions_native.py](../tools/verify_battle_turn_regressions_native.py) | Original 3B reader on human/canine fog snapshots; rendering is stubbed. |
| [tools/verify_battle_turn_remote.py](../tools/verify_battle_turn_remote.py) | Run focused tests in an isolated copy of the actual hosted code. |
| [tools/verify_battle_ui_hd_native.py](../tools/verify_battle_ui_hd_native.py) | Execute the item loaders and real native HD quad/UV pipeline in Unicorn. |
| [tools/verify_bot_credit_rewards_health_remote.py](../tools/verify_bot_credit_rewards_health_remote.py) | Read-only final health/source/save comparison. Run on the hosted server. |
| [tools/verify_bot_credit_rewards_hosted.py](../tools/verify_bot_credit_rewards_hosted.py) | Owned, excluded QA accounts exercise credit receipts through hosted TLS. |
| [tools/verify_bot_finishing_health_remote.py](../tools/verify_bot_finishing_health_remote.py) | Read-only final health/source/save comparison. Run on the hosted server. |
| [tools/verify_bot_finishing_hosted.py](../tools/verify_bot_finishing_hosted.py) | Screenshot regressions and multiplayer bot gameplay over hosted TLS. |
| [tools/verify_character_create_native.py](../tools/verify_character_create_native.py) | Original result parser with UI/logging/localization stubs, all status branches. |
| [tools/verify_character_record_native.py](../tools/verify_character_record_native.py) | Original nonempty10 parser and nested6d01f8. UI/lifecycle/property calls and CString conversion stubbed. |
| [tools/verify_character_select_native.py](../tools/verify_character_select_native.py) | Original empty10 parser and export gate; UI/record lifecycle explicitly stubbed. |
| [tools/verify_chat_layout_native.py](../tools/verify_chat_layout_native.py) | Execute existing Silver chat geometry code without launching a game. |
| [tools/verify_cities_native.py](../tools/verify_cities_native.py) | Original silver.dll ground reader consumes all generated city packets. |
| [tools/verify_cities_remote.py](../tools/verify_cities_remote.py) | Run focused tests in an isolated copy of the actual hosted code. |
| [tools/verify_city_catalogs_native.py](../tools/verify_city_catalogs_native.py) | Execute TI city dispatch/readers; stub allocation, string conversion and UI only. |
| [tools/verify_city_hand_drag_native.py](../tools/verify_city_hand_drag_native.py) | Original hand-to-hand drag branch a6641d; stop before unrelated UI refresh. |
| [tools/verify_city_interface_hosted.py](../tools/verify_city_interface_hosted.py) | Run city operations against disposable hosted saves and private fixtures. |
| [tools/verify_city_inventory_network_hosted.py](../tools/verify_city_inventory_network_hosted.py) | Exercise the observed city33 fix in a disposable hosted network server. |
| [tools/verify_city_requests_native.py](../tools/verify_city_requests_native.py) | Original shop991940 and warehouse9921a8 builders; transport/UI bookkeeping isolated. |
| [tools/verify_clan_crest_native.py](../tools/verify_clan_crest_native.py) | Read-only original Silver/ti.exe crest transport and cache proof. |
| [tools/verify_clan_portal_hosted.py](../tools/verify_clan_portal_hosted.py) | Owned-session HTTPS reads and guaranteed-invalid crest/webhook requests. |
| [tools/verify_clan_warfare_candidate.py](../tools/verify_clan_warfare_candidate.py) | Prepare locally, then test an owned copy of hosted code with a pinned overlay. |
| [tools/verify_clan_warfare_native.py](../tools/verify_clan_warfare_native.py) | Local-only original Silver wire proof. No processes, sockets or callbacks. |
| [tools/verify_clans_native.py](../tools/verify_clans_native.py) | Execute original clan builders/readers with explicit string/allocation/UI stubs. |
| [tools/verify_clans_remote.py](../tools/verify_clans_remote.py) | Run focused tests in an isolated copy of the actual hosted code. |
| [tools/verify_client_screen_settings_native.py](../tools/verify_client_screen_settings_native.py) | Execute Screen snapshot/Apply x86 hooks with explicit native UI/D3D stubs. |
| [tools/verify_client_ui_hd_fonts_native.py](../tools/verify_client_ui_hd_fonts_native.py) | Offline x86 execution of the selected font adapter and original TI renderer. |
| [tools/verify_client_ui_scale_native.py](../tools/verify_client_ui_scale_native.py) | Execute UI-scale native x86 with explicit Windows, renderer and UI stubs. |
| [tools/verify_client_ui_scale_static.py](../tools/verify_client_ui_scale_static.py) | Independent ABI and rendering-boundary proof for the native UI scale core. |
| [tools/verify_combat_distance_native.py](../tools/verify_combat_distance_native.py) | Execute original a8907c including native square root and integer rounding. |
| [tools/verify_completion_native.py](../tools/verify_completion_native.py) | Original transport02 branch, queue call captured rather than executing allocator. |
| [tools/verify_connection_liveness_linux.py](../tools/verify_connection_liveness_linux.py) | Run only inside a disposable Linux network namespace (unshare -n). |
| [tools/verify_contest_maps_native.py](../tools/verify_contest_maps_native.py) | Published DLL ground-reader proof; resource loading/GPU are explicit stubs. |
| [tools/verify_contracts_city_graphical.py](../tools/verify_contracts_city_graphical.py) | Own two graphical clients against a private SQLite copy and loopback only. |
| [tools/verify_contracts_city_native.py](../tools/verify_contracts_city_native.py) | Build and verify a pinned native city candidate, without client installation. |
| [tools/verify_contracts_local.py](../tools/verify_contracts_local.py) | Run bounded local checks and save their actual results without any hosting I/O. |
| [tools/verify_corpse_visibility_native.py](../tools/verify_corpse_visibility_native.py) | Original corpse HP transition and owner elimination predicate; rendering isolated. |
| [tools/verify_crate_visual_native.py](../tools/verify_crate_visual_native.py) | Execute original ti.exe44 scene consumer and crate frame selection. |
| [tools/verify_creation_presentation_native.py](../tools/verify_creation_presentation_native.py) | Execute presentation detours and native model selection; renderer calls stubbed. |
| [tools/verify_crystal_history_native.py](../tools/verify_crystal_history_native.py) | Execute original B01F reader and append actual four-float quote records. |
| [tools/verify_dog_abilities_native.py](../tools/verify_dog_abilities_native.py) | Execute original door permission predicates and rejected-move recovery. |
| [tools/verify_dog_battle_native.py](../tools/verify_dog_battle_native.py) | Saved hire-dog66 -> battle3B original reader; scene/UI helpers isolated. |
| [tools/verify_empty_item_list_native.py](../tools/verify_empty_item_list_native.py) | Original ItemList30 decoder63ce00, empty array branch (no allocation stubs). |
| [tools/verify_encounter_native.py](../tools/verify_encounter_native.py) | Original x86 dog packet reader; UI, allocation and renderer are stubbed. |
| [tools/verify_encounters_candidate_remote.py](../tools/verify_encounters_candidate_remote.py) | Run focused candidate tests against the actual hosted code plus its overlay. |
| [tools/verify_end_turn_native.py](../tools/verify_end_turn_native.py) | Original95e08c EndTurn sender: gates, own actor scan, writers and cooldown. |
| [tools/verify_english_localization_hosted.py](../tools/verify_english_localization_hosted.py) | Two disposable, ranking-excluded accounts verify RU/EN on production TLS. |
| [tools/verify_english_resources.py](../tools/verify_english_resources.py) | Read-only verification of every published language resource over trusted HTTPS. |
| [tools/verify_enhancement_native.py](../tools/verify_enhancement_native.py) | Execute original enhancement writer, inventory getters and x87 stat arithmetic. |
| [tools/verify_equip_request_native.py](../tools/verify_equip_request_native.py) | Verify the original Wear button callback and item action33 writer separately. |
| [tools/verify_equipable_default_native.py](../tools/verify_equipable_default_native.py) | Original XML equipable access, missing-key helper branch and metadata write. |
| [tools/verify_equipment_ajpg_native.py](../tools/verify_equipment_ajpg_native.py) | Run ti.exe's original AJPG decrypt loop; retain original masks and header fields. |
| [tools/verify_equipment_batch_native.py](../tools/verify_equipment_batch_native.py) | Execute candidate PE equipment extension plus original33/OK paths. |
| [tools/verify_equipment_confirmation_native.py](../tools/verify_equipment_confirmation_native.py) | Check original inventory OK, generic OnHide and immediate action33 writes. |
| [tools/verify_equipment_double_click_native.py](../tools/verify_equipment_double_click_native.py) | Original equipment widget DoMouseDoubleClick for backpack/equipped items. |
| [tools/verify_equipment_effects_native.py](../tools/verify_equipment_effects_native.py) | Execute original XML generic bonus construction; isolate Delphi allocation/string helpers. |
| [tools/verify_equipment_templates_native.py](../tools/verify_equipment_templates_native.py) | Execute original C5 builders and list/view readers, with UI/allocator stubs. |
| [tools/verify_equipment_texture_assets.py](../tools/verify_equipment_texture_assets.py) | Check the whole equipment overlay, including native alpha and D3DX allocations. |
| [tools/verify_equipment_texture_loader_native.py](../tools/verify_equipment_texture_loader_native.py) | Execute the original memory-texture loader's D3DX argument assembly in Unicorn. |
| [tools/verify_finish_results_native.py](../tools/verify_finish_results_native.py) | Verify F0/449 dispatch and original result-close/scene-event13 branch. |
| [tools/verify_fog_lobby_native.py](../tools/verify_fog_lobby_native.py) | Original x86 fog reset/reveal and F0 Unicode argument parsing. |
| [tools/verify_forest_candidate_remote.py](../tools/verify_forest_candidate_remote.py) | Run focused candidate tests against the actual hosted code plus its overlay. |
| [tools/verify_forest_native.py](../tools/verify_forest_native.py) | Original x86 ground brush selection and item quantity gates; renderer stubbed. |
| [tools/verify_forest_release.py](../tools/verify_forest_release.py) | Read-only HTTPS release and hosted service/database checks. |
| [tools/verify_frozen_public_hosted.py](../tools/verify_frozen_public_hosted.py) | Verify a frozen release in disposable hosted trees, never hosted saves. |
| [tools/verify_frozen_public_local.py](../tools/verify_frozen_public_local.py) | Run explicit tests against an immutable public runtime with disposable saves. |
| [tools/verify_game_operations_hosted.py](../tools/verify_game_operations_hosted.py) | Verify shared service commands with two disposable production TLS accounts. |
| [tools/verify_game_tls_bootstrap_x86.py](../tools/verify_game_tls_bootstrap_x86.py) | Independently execute actual generated launcher bootstrap bytes in Unicorn. |
| [tools/verify_game_tls_hosted.py](../tools/verify_game_tls_hosted.py) | Bounded TLS probes and two owned-account hosted protocol validation. |
| [tools/verify_game_tls_pcap.py](../tools/verify_game_tls_pcap.py) | Inspect bounded owned-client game TLS pcap without decrypting or logging secrets. |
| [tools/verify_game_tls_route_native.py](../tools/verify_game_tls_route_native.py) | Execute the launcher's actual x86 destination thunk in Unicorn. |
| [tools/verify_generated_avatars_native.py](../tools/verify_generated_avatars_native.py) | Native avatar catalog/category/selection and FC checks; GUI/GPU are stubbed. |
| [tools/verify_global_map_filter.py](../tools/verify_global_map_filter.py) | Execute actual x86 mip/IAT/SEH cleanup and sampler thunks in Unicorn. |
| [tools/verify_global_map_graphical.py](../tools/verify_global_map_graphical.py) | Owned global-map graphical QA using the established TLS/native-auth harness. |
| [tools/verify_global_map_native.py](../tools/verify_global_map_native.py) | Execute the real appended x86 projection, drawing scope and picking in Unicorn. |
| [tools/verify_ground_loot_native.py](../tools/verify_ground_loot_native.py) | Execute original empty-ground UI branch, ground44/45 scene reader and bag renderer. |
| [tools/verify_health_native.py](../tools/verify_health_native.py) | Original4E serializer and status4 store; UI/effect callbacks not executed. |
| [tools/verify_hire_request_native.py](../tools/verify_hire_request_native.py) | Original request builder8c3c34; packet-buffer and UI helpers are stubs. |
| [tools/verify_hosted_achievement_city_fix.py](../tools/verify_hosted_achievement_city_fix.py) | Two disposable excluded TLS accounts test the deployed non-city delivery guard. |
| [tools/verify_hosted_admission_capacity.py](../tools/verify_hosted_admission_capacity.py) | Bounded checks of the actual hosted service, using two fresh QA accounts. |
| [tools/verify_hosted_arena_gears.py](../tools/verify_hosted_arena_gears.py) | Two fresh accounts on public encrypted TCP; no graphical-client claim. |
| [tools/verify_hosted_arena_surroundings.py](../tools/verify_hosted_arena_surroundings.py) | Verify shared hosted arena art over public encrypted TCP after deployment. |
| [tools/verify_hosted_battle_core.py](../tools/verify_hosted_battle_core.py) | Five fresh hosted accounts: 2v2 combat/reconnect/chat and a city outsider. |
| [tools/verify_hosted_battle_exchange.py](../tools/verify_hosted_battle_exchange.py) | Two fresh hosted accounts, each with two mercenaries, share a Team battle. |
| [tools/verify_hosted_battle_items.py](../tools/verify_hosted_battle_items.py) | Four ordinary hosted accounts buy/use smoke and flash through native TLS. |
| [tools/verify_hosted_battle_recovery.py](../tools/verify_hosted_battle_recovery.py) | Public two-account gameplay plus read-only durable-state checks on the VPS. |
| [tools/verify_hosted_battle_turn_regressions.py](../tools/verify_hosted_battle_turn_regressions.py) | Public encrypted TCP with two fresh accounts, real moves and bot attacks. |
| [tools/verify_hosted_captcha.py](../tools/verify_hosted_captcha.py) | Check live CAPTCHA rejection and login with an existing owned QA fixture. |
| [tools/verify_hosted_character_onboarding.py](../tools/verify_hosted_character_onboarding.py) | Register two temporary QA accounts over HTTPS and test public encrypted game TCP. |
| [tools/verify_hosted_chat_presence.py](../tools/verify_hosted_chat_presence.py) | Three fresh hosted accounts, public encrypted TCP; not graphical clients. |
| [tools/verify_hosted_cities.py](../tools/verify_hosted_cities.py) | Fresh authenticated accounts over public TCP; graphical clients not exercised. |
| [tools/verify_hosted_city_readonly.py](../tools/verify_hosted_city_readonly.py) | Read actual private city HTTP for the retained owned pair; no mutations. |
| [tools/verify_hosted_city_transactions.py](../tools/verify_hosted_city_transactions.py) | Ordinary one-stock buy/replay/sell through live HTTP for the owned pair. |
| [tools/verify_hosted_clan_completion.py](../tools/verify_hosted_clan_completion.py) | Read-only clan/world QA on the retained ordinary phase5/6 pair. |
| [tools/verify_hosted_clan_warfare.py](../tools/verify_hosted_clan_warfare.py) | Two ordinary new accounts: verified TLS, standings/profiles and denied rooms. |
| [tools/verify_hosted_clans.py](../tools/verify_hosted_clans.py) | Three fresh accounts on public encrypted TCP; no graphical-client claim. |
| [tools/verify_hosted_combat.py](../tools/verify_hosted_combat.py) | Two fresh HTTPS accounts exercise the deployed Wall over public encrypted TCP. |
| [tools/verify_hosted_corpse_visibility.py](../tools/verify_hosted_corpse_visibility.py) | Public mine entry with two fresh QA accounts; no graphical clients. |
| [tools/verify_hosted_durability.py](../tools/verify_hosted_durability.py) | Two fresh HTTPS accounts exercise the deployed Wall over public encrypted TCP. |
| [tools/verify_hosted_economy_completion.py](../tools/verify_hosted_economy_completion.py) | Ordinary shared economy QA on the preserved phase5 pair, over verified TLS. |
| [tools/verify_hosted_economy_tls.py](../tools/verify_hosted_economy_tls.py) | Owned two-account economy acceptance over verified gameplay TLS. |
| [tools/verify_hosted_email_registration.py](../tools/verify_hosted_email_registration.py) | Verify hosted email gating with one owned QA account and a simulated mailbox. |
| [tools/verify_hosted_encounter_return.py](../tools/verify_hosted_encounter_return.py) | Two fresh hosted accounts die in natural encounters over encrypted public TCP. |
| [tools/verify_hosted_encounters.py](../tools/verify_hosted_encounters.py) | Two fresh hosted accounts encounter and fight dogs through public encrypted TCP. |
| [tools/verify_hosted_equipment_batch.py](../tools/verify_hosted_equipment_batch.py) | Verify the deployed batch through four ordinary owned TLS game sessions. |
| [tools/verify_hosted_fog_lobbies.py](../tools/verify_hosted_fog_lobbies.py) | Two fresh hosted accounts: wounded rejection, paid heal, Team/Wall creation, |
| [tools/verify_hosted_forest_biomes.py](../tools/verify_hosted_forest_biomes.py) | Fresh real hosted accounts, encrypted TCP gameplay/loot/shop/shared auction. |
| [tools/verify_hosted_gameplay_modes.py](../tools/verify_hosted_gameplay_modes.py) | Four fresh owned accounts: FFA and wagers through verified native TLS. |
| [tools/verify_hosted_graphical_bridge_browsing_visible.py](../tools/verify_hosted_graphical_bridge_browsing_visible.py) | Read-only native validation; no Frida, game process, login or connection. |
| [tools/verify_hosted_graphical_bridge_empty_roster.py](../tools/verify_hosted_graphical_bridge_empty_roster.py) | Read-only native validation; no Frida, game process, login or connection. |
| [tools/verify_hosted_graphical_bridge_search_status.py](../tools/verify_hosted_graphical_bridge_search_status.py) | Read-only native validation; no Frida, game process, login or connection. |
| [tools/verify_hosted_ground_equipment.py](../tools/verify_hosted_ground_equipment.py) | Two fresh QA accounts exercise deployed ground loot over public encrypted TCP. |
| [tools/verify_hosted_ground_loot.py](../tools/verify_hosted_ground_loot.py) | Two fresh QA accounts exercise deployed ground loot over public encrypted TCP. |
| [tools/verify_hosted_login_denials.py](../tools/verify_hosted_login_denials.py) | Bounded TLS login checks using two existing owned QA accounts only. |
| [tools/verify_hosted_login_display.py](../tools/verify_hosted_login_display.py) | Fresh QA saves and public encrypted TCP; no graphical-client claim. |
| [tools/verify_hosted_mine_completion.py](../tools/verify_hosted_mine_completion.py) | Owned Lv4 TLS accounts: actual shared mine, second raider and price history. |
| [tools/verify_hosted_mine_hunter.py](../tools/verify_hosted_mine_hunter.py) | Two retained owned accounts exercise deployed mine hunters over strict TLS. |
| [tools/verify_hosted_mines_expiry.py](../tools/verify_hosted_mines_expiry.py) | One fresh owned TLS mine, then real 180-second offline expiry, read-only. |
| [tools/verify_hosted_player_statistics.py](../tools/verify_hosted_player_statistics.py) | Shared PvP and profile fields over the public encrypted TCP transport. |
| [tools/verify_hosted_post_battle_treatment.py](../tools/verify_hosted_post_battle_treatment.py) | Two fresh QA accounts fight over public encrypted TCP and heal after Finish. |
| [tools/verify_hosted_premium.py](../tools/verify_hosted_premium.py) | Two fresh QA accounts on public encrypted TCP; not a graphical-client test. |
| [tools/verify_hosted_ranked.py](../tools/verify_hosted_ranked.py) | Two fresh real accounts over encrypted TCP; no bots or graphical-client claim. |
| [tools/verify_hosted_reservation_maps.py](../tools/verify_hosted_reservation_maps.py) | Two fresh HTTPS accounts exercise the deployed Reservation maps over public encrypted TCP. |
| [tools/verify_hosted_reservation_textures.py](../tools/verify_hosted_reservation_textures.py) | Two fresh HTTPS accounts exercise the deployed Reservation maps over public encrypted TCP. |
| [tools/verify_hosted_rewards.py](../tools/verify_hosted_rewards.py) | Two fresh HTTPS accounts exercise the deployed Wall over native public TCP with legacy obfuscation. |
| [tools/verify_hosted_roster_completion.py](../tools/verify_hosted_roster_completion.py) | Ordinary owned-account roster/tutorial QA over verified hosted TLS. |
| [tools/verify_hosted_services_auction.py](../tools/verify_hosted_services_auction.py) | Two fresh hosted accounts through public encrypted TCP; no graphical client. |
| [tools/verify_hosted_services_http.py](../tools/verify_hosted_services_http.py) | Owner-bound Services V2 HTTP checks using ordinary free no-op receipts. |
| [tools/verify_hosted_services_portal.py](../tools/verify_hosted_services_portal.py) | Check the published portal anonymously over trusted HTTPS and local health. |
| [tools/verify_hosted_shared_mines.py](../tools/verify_hosted_shared_mines.py) | Three owned ordinary protocol clients in one isolated production TLS mine. |
| [tools/verify_hosted_shop_prices.py](../tools/verify_hosted_shop_prices.py) | Public encrypted TCP shopping with two fresh QA accounts; no player credentials. |
| [tools/verify_hosted_spectator.py](../tools/verify_hosted_spectator.py) | Three fresh TCP accounts: kill the sole fighter, spectate, leave. |
| [tools/verify_hosted_stage12_http.py](../tools/verify_hosted_stage12_http.py) | Owner-bound stage12 read-only HTTP acceptance; root runs it after deployment. |
| [tools/verify_hosted_stage7.py](../tools/verify_hosted_stage7.py) | Two owned new accounts: ordinary characters/mail/standings over strict TLS. |
| [tools/verify_hosted_team_balance.py](../tools/verify_hosted_team_balance.py) | Public encrypted TCP: unequal selected squads enter with equal numbers. |
| [tools/verify_hosted_team_heartbeat.py](../tools/verify_hosted_team_heartbeat.py) | Two fresh HTTPS accounts exercise the deployed Wall over public encrypted TCP. |
| [tools/verify_hosted_team_start.py](../tools/verify_hosted_team_start.py) | Two independent hosted accounts reproduce one-versus-two selected squads. |
| [tools/verify_hosted_turn_order.py](../tools/verify_hosted_turn_order.py) | Two fresh QA accounts exercise deployed shared battles over public encrypted TCP. |
| [tools/verify_hosted_turn_timer.py](../tools/verify_hosted_turn_timer.py) | Two hosted accounts: native-compatible timer handoff in Team and Wall. |
| [tools/verify_hosted_wall_spectator.py](../tools/verify_hosted_wall_spectator.py) | Three fresh TCP accounts: kill the sole fighter, spectate, leave. |
| [tools/verify_hosted_warehouse_queries.py](../tools/verify_hosted_warehouse_queries.py) | Two fresh QA accounts exercise deployed warehouse queries over public encrypted TCP. |
| [tools/verify_hosted_weapon_effects.py](../tools/verify_hosted_weapon_effects.py) | Two fresh QA accounts exercise deployed weapon effects over public encrypted TCP. |
| [tools/verify_hosted_world_completion.py](../tools/verify_hosted_world_completion.py) | Phase8 native TLS QA using the retained ordinary phase5/6 pair. |
| [tools/verify_inventory_layout_native.py](../tools/verify_inventory_layout_native.py) | Execute original inventory/scrollbar geometry routines without a game client. |
| [tools/verify_inventory_slots_native.py](../tools/verify_inventory_slots_native.py) | Original inventory slot normalization99082a..9908b4 plus RTTI names. |
| [tools/verify_item_action_route_native.py](../tools/verify_item_action_route_native.py) | Original997260 action routes to920068 and bypasses legacy6B block. |
| [tools/verify_item_batch_native.py](../tools/verify_item_batch_native.py) | Original992294 writer6B; list allocation/refcounts/UI isolated, writers run. |
| [tools/verify_armor_reduction_native.py](../tools/verify_armor_reduction_native.py) | Original target-armor damage reduction a7aa58 against a Python model. |
| [tools/verify_item_mark_window_native.py](../tools/verify_item_mark_window_native.py) | Original item-mark window builders (B8 01/02/03) and MarkedItems writer C829. |
| [tools/verify_item_marks_native.py](../tools/verify_item_marks_native.py) | Execute original ItemRecord reader and owner/TTL getters in pinned silver.dll. |
| [tools/verify_item_policy_native.py](../tools/verify_item_policy_native.py) | Run a6516c with isolated UI/lifetime and synthetic ordinary-item metadata. |
| [tools/verify_item_record_native.py](../tools/verify_item_record_native.py) | Execute original item-record63bd38 with both optional-u32 branches. |
| [tools/verify_item_required_level_native.py](../tools/verify_item_required_level_native.py) | Original required-level function A7C500, with synthetic template metadata. |
| [tools/verify_item_stacking_native.py](../tools/verify_item_stacking_native.py) | Original item count parser, stack metadata write and quantity-dialog gates. |
| [tools/verify_item_target_native.py](../tools/verify_item_target_native.py) | Execute original a7a050 target-control mask to action33 option conversion. |
| [tools/verify_item_type_native.py](../tools/verify_item_type_native.py) | Original item type classification a713cf..a719a8. |
| [tools/verify_known_mines_native.py](../tools/verify_known_mines_native.py) | Original658bc8/658824 writes known mines; real writers, no stubs. |
| [tools/verify_launcher_014_offsite.py](../tools/verify_launcher_014_offsite.py) | Independently verify a DPAPI copy and reviewed launcher/portal identities. |
| [tools/verify_launcher_doors_native.py](../tools/verify_launcher_doors_native.py) | Execute the exact C# launcher payload in original ti.exe memory. |
| [tools/verify_legacy_degrain_assets.py](../tools/verify_legacy_degrain_assets.py) | Read-only independent contract/native proof review for imagegen asset export. |
| [tools/verify_legacy_lobbies_hosted.py](../tools/verify_legacy_lobbies_hosted.py) | Four fresh owned accounts verify hosted legacy lobbies through verified TLS. |
| [tools/verify_legacy_lobbies_native.py](../tools/verify_legacy_lobbies_native.py) | Execute legacy list decoding, level projection, colours and join in x86. |
| [tools/verify_legacy_lobbies_release_health.py](../tools/verify_legacy_lobbies_release_health.py) | Read-only final health check for the hosted legacy-client release. |
| [tools/verify_legacy_lobbies_runtime.py](../tools/verify_legacy_lobbies_runtime.py) | Check a bounded lobby candidate against actual hosted code and catalogs. |
| [tools/verify_legacy_member_leave_native.py](../tools/verify_legacy_member_leave_native.py) | Original wire25 merge and wire27 removal, executed at two real PE bases. |
| [tools/verify_legacy_project_agreement_native.py](../tools/verify_legacy_project_agreement_native.py) | Read-only verification of the unchanged legacy agreement loader and CRC32. |
| [tools/verify_legacy_server_freshness_native.py](../tools/verify_legacy_server_freshness_native.py) | Execute native server-list refresh, response recovery and stale rendering. |
| [tools/verify_legacy_server_status_native.py](../tools/verify_legacy_server_status_native.py) | Execute actual legacy list06 decoder, complete row renderer and formatter. |
| [tools/verify_level_progression_native.py](../tools/verify_level_progression_native.py) | Execute original XP table lookup, NextLvl_Exp and4E XP model write. |
| [tools/verify_login_failure_native.py](../tools/verify_login_failure_native.py) | Execute the pinned original LSLoginResult error consumer; no game or sockets. |
| [tools/verify_mail_native.py](../tools/verify_mail_native.py) | Unchanged original Silver numeric mail builders/readers in bounded Unicorn. |
| [tools/verify_main_hud_degrain_assets.py](../tools/verify_main_hud_degrain_assets.py) | Read-only independent verification of the scoped native HUD asset package. |
| [tools/verify_map_motion_native.py](../tools/verify_map_motion_native.py) | Original moving1D, stop1E, map step9EDD18 and visual interpolation9EDF92. |
| [tools/verify_members_arranged_native.py](../tools/verify_members_arranged_native.py) | Native71 dispatcher, order reader, sorting and name-row numeric argument. |
| [tools/verify_mine_drill_actions_native.py](../tools/verify_mine_drill_actions_native.py) | Execute native drill click, quantity-dialog arguments and both wire writers. |
| [tools/verify_mine_help_catalog_native.py](../tools/verify_mine_help_catalog_native.py) | Original skill XML catalogue loader and default skill28 atlas selection. |
| [tools/verify_mine_help_native.py](../tools/verify_mine_help_native.py) | Original radio skill GUI, mining queue writers/readers and lobby state. |
| [tools/verify_mine_hover_scale_native.py](../tools/verify_mine_hover_scale_native.py) | Execute the original mine hit detector with physical and logical mice. |
| [tools/verify_mine_path_entry_native.py](../tools/verify_mine_path_entry_native.py) | Execute the exact scene-entry candidate, including TI's original reset. |
| [tools/verify_mine_path_preview_native.py](../tools/verify_mine_path_preview_native.py) | Read-only execution of actual TI picking, AP truncation and foot geometry. |
| [tools/verify_miner_abilities_native.py](../tools/verify_miner_abilities_native.py) | Original81/4B/AA and PetInfo readers for all four miner ranks. |
| [tools/verify_miner_learning_ui_native.py](../tools/verify_miner_learning_ui_native.py) | Run original skill-grid click and Learn-button logic (8AE5C4, 8AD160). |
| [tools/verify_miner_native.py](../tools/verify_miner_native.py) | Original map writer1B, movement reader1D, hire62 and PetInfo66. |
| [tools/verify_mining_native.py](../tools/verify_mining_native.py) | Run original mining readers; isolate UI, allocation and collection adapters. |
| [tools/verify_miss_native.py](../tools/verify_miss_native.py) | Execute original result selection and floating-text branch in silver.dll. |
| [tools/verify_mode1_native.py](../tools/verify_mode1_native.py) | Original09 dispatcher/key derivation/builders; send1c90 stubbed. |
| [tools/verify_move_request_native.py](../tools/verify_move_request_native.py) | Original ti.exe6dc460 C2S3C writer; transport/critical sections isolated. |
| [tools/verify_native_live_arena_list_consumers.py](../tools/verify_native_live_arena_list_consumers.py) | Execute complete original BA dispatcher, merge/delete and actual colour refresh. |
| [tools/verify_native_lobby_departure_sequence.py](../tools/verify_native_lobby_departure_sequence.py) | Execute actual native25 merge and27 clear for decoded two-account TCP streams. |
| [tools/verify_native_login_observer.py](../tools/verify_native_login_observer.py) | Exercise passive observer guards/counter cleanup with isolated Node doubles. |
| [tools/verify_new_player_client_install.py](../tools/verify_new_player_client_install.py) | Read-only size/SHA256 verification of a launcher-installed client. |
| [tools/verify_normal_ti_connect_native.py](../tools/verify_normal_ti_connect_native.py) | Isolated original TI Unicode adapter -> TLS thunk -> ORANGE byte-mode proof. |
| [tools/verify_nvg_client_native.py](../tools/verify_nvg_client_native.py) | Execute F9 snapshot and original inventory/AP/native33 paths in x86. |
| [tools/verify_onboarding_client_native.py](../tools/verify_onboarding_client_native.py) | Run patched original status/list hooks in x86, including a relocated image. |
| [tools/verify_original_names_departure_sequence_native.py](../tools/verify_original_names_departure_sequence_native.py) | Reuse the immutable original25/27 consumer against new candidate TCP evidence. |
| [tools/verify_owned_d_dual_negative_fixture.py](../tools/verify_owned_d_dual_negative_fixture.py) | Exercise reviewed QA packet edits and cancellation on an isolated SQLite fixture. |
| [tools/verify_owned_ui_connection_continuity.py](../tools/verify_owned_ui_connection_continuity.py) | Read-only process/TCP continuity proof for explicitly identified owned A/B QA. |
| [tools/verify_pet_info_native.py](../tools/verify_pet_info_native.py) | Verify encoded PetInfo66 across new/existing slots and eight body profiles. |
| [tools/verify_pet_state_native.py](../tools/verify_pet_state_native.py) | Original67 sender and mercenary selector predicate; transport isolated. |
| [tools/verify_player_auction_native.py](../tools/verify_player_auction_native.py) | Original auction readers with managed allocation/string stubs only. |
| [tools/verify_player_statistics_state_remote.py](../tools/verify_player_statistics_state_remote.py) | Hosting-only persistence audit; refuses to interrupt active game clients. |
| [tools/verify_player_top100_native.py](../tools/verify_player_top100_native.py) | Execute original player-rating combo/builder/reader and refresh lookup. |
| [tools/verify_player_trade_hosted.py](../tools/verify_player_trade_hosted.py) | Three disposable excluded accounts verify native barter through production TLS. |
| [tools/verify_player_trade_native.py](../tools/verify_player_trade_native.py) | Execute the published native barter writers/readers with explicit UI stubs. |
| [tools/verify_portal_hosted.py](../tools/verify_portal_hosted.py) | Black-box portal checks over trusted HTTPS; optional owned QA fixtures only. |
| [tools/verify_portal_registration_rollout.py](../tools/verify_portal_registration_rollout.py) | Record final read-only hosted account-preservation and service evidence. |
| [tools/verify_portrait_quality_native.py](../tools/verify_portrait_quality_native.py) | Execute portrait extension x86 at two ASLR bases; native GUI/COM calls stubbed. |
| [tools/verify_post_battle_finish_native.py](../tools/verify_post_battle_finish_native.py) | Original Finish callback719F60 and treatment sender8C3D84. |
| [tools/verify_premium_native.py](../tools/verify_premium_native.py) | Original buy-button writer and subscription-status consumer; UI/transport stubs only. |
| [tools/verify_premium_shop_native.py](../tools/verify_premium_shop_native.py) | Execute original Gold-shop readers/consumer and request writer; UI isolated. |
| [tools/verify_presence_native.py](../tools/verify_presence_native.py) | Execute original C7/4F/51 readers; stub string allocation and UI only. |
| [tools/verify_private_market_native.py](../tools/verify_private_market_native.py) | Pinned original x86 private-store and SC builders; real numeric wire writers. |
| [tools/verify_proficiency_decrease_native.py](../tools/verify_proficiency_decrease_native.py) | Execute original decrease GUI callbacks and original chat21 serialization. |
| [tools/verify_public_runtime_regression.py](../tools/verify_public_runtime_regression.py) | Run repository public gameplay tests on an immutable hosted source snapshot. |
| [tools/verify_published_game_tls_launcher.py](../tools/verify_published_game_tls_launcher.py) | Verify the public launcher through normal HTTPS without saving or executing it. |
| [tools/verify_published_launcher_014.py](../tools/verify_published_launcher_014.py) | Read-only trusted HTTPS proof of both reviewed 0.1.4 downloads and metadata. |
| [tools/verify_published_launcher_update.py](../tools/verify_published_launcher_update.py) | Read-only trusted HTTPS and hosted-state verification of a launcher release. |
| [tools/verify_qa_native_multinstance.py](../tools/verify_qa_native_multinstance.py) | Bounded original startup branch probe for the two-branch own QA bypass. |
| [tools/verify_quest_ack_native.py](../tools/verify_quest_ack_native.py) | Execute the published native ACK dispatcher/reader; UI and audio are stubs. |
| [tools/verify_rain_weather_native.py](../tools/verify_rain_weather_native.py) | Execute the released-chain candidate's x86 rain parser/draw callbacks. |
| [tools/verify_ranked_native.py](../tools/verify_ranked_native.py) | Original x86 TrueSkill builder, score readers and flag-color callback. |
| [tools/verify_ranked_remote.py](../tools/verify_ranked_remote.py) | Run focused tests in an isolated copy of the actual hosted code. |
| [tools/verify_ranks_native.py](../tools/verify_ranks_native.py) | Read real rank packets through original silver.dll 66/3B handlers in Unicorn. |
| [tools/verify_rating_completion_native.py](../tools/verify_rating_completion_native.py) | Execute original C6/21 builder and C6/04 numeric roster reader. |
| [tools/verify_rating_completion_shared_case.py](../tools/verify_rating_completion_shared_case.py) | Run one approved stale ABI assertion correction on exact frozen runtime. |
| [tools/verify_ratings_portal_web.py](../tools/verify_ratings_portal_web.py) | Record focused read-only portal checks without touching game data or services. |
| [tools/verify_rental_native.py](../tools/verify_rental_native.py) | Execute original rental dispatcher, numeric consumer and request writers in Unicorn. |
| [tools/verify_repair_native.py](../tools/verify_repair_native.py) | Execute original repair writers and durability getters; transport/UI stubs only. |
| [tools/verify_reservation_assets.py](../tools/verify_reservation_assets.py) | Verify exact geometry, original alpha masks and isolated resource bindings. |
| [tools/verify_reservation_candidate_remote.py](../tools/verify_reservation_candidate_remote.py) | Candidate source overlay checks without touching hosted player data. |
| [tools/verify_reservation_crate_alpha_release.py](../tools/verify_reservation_crate_alpha_release.py) | Read-only verification of the public transparency patch and hosted health. |
| [tools/verify_reservation_release.py](../tools/verify_reservation_release.py) | Read-only HTTPS release and hosted service/database checks. |
| [tools/verify_room_actions_native.py](../tools/verify_room_actions_native.py) | Original main-room ready toggle, leave and start builders (not BA family). |
| [tools/verify_roster_progression_native.py](../tools/verify_roster_progression_native.py) | Read actual durable random hires and service tiers through original x86. |
| [tools/verify_russian_encoding_native.py](../tools/verify_russian_encoding_native.py) | Execute the original/patched Delphi codepage initialization in Unicorn. |
| [tools/verify_sc_receiver_native.py](../tools/verify_sc_receiver_native.py) | Bounded original-client SC receive-route proof, not a reconstructed BD ABI. |
| [tools/verify_sc_shop_native.py](../tools/verify_sc_shop_native.py) | Original SC numeric readers/writers and catalog consumer; allocator/UI isolated. |
| [tools/verify_sc_view_native.py](../tools/verify_sc_view_native.py) | Execute the reviewed F8 extension and original SC filter/UI callbacks. |
| [tools/verify_screen_settings_graphical.py](../tools/verify_screen_settings_graphical.py) | Owned native Screen QA; no startup on import, --help or check-only. |
| [tools/verify_server_list_native.py](../tools/verify_server_list_native.py) | Execute original06 parser, primitive readers and empty CString reader. |
| [tools/verify_server_login_native.py](../tools/verify_server_login_native.py) | Original08 dispatcher/parser; UI/string helpers/connect callback stubbed. |
| [tools/verify_services_native.py](../tools/verify_services_native.py) | Execute original B1/01 reader and B1/03 dispatcher, stubbing UI only. |
| [tools/verify_shared_config_data_native.py](../tools/verify_shared_config_data_native.py) | Original B9/03 dispatcher and reads/copy, stopped before filesystem operations. |
| [tools/verify_shared_config_native.py](../tools/verify_shared_config_native.py) | Original B9 dispatcher and manifest readers; strings/list/loading explicitly stubbed. |
| [tools/verify_shared_mines_final_health.py](../tools/verify_shared_mines_final_health.py) | Read-only final hosted service, source and maintenance-cleanup verification. |
| [tools/verify_shared_mines_native.py](../tools/verify_shared_mines_native.py) | Bounded original x86 mining/currency ABI proof; no network or native UI actions. |
| [tools/verify_shooting_range_native.py](../tools/verify_shooting_range_native.py) | Execute original mode16 entry/start builders. Only transport/UI are stubbed. |
| [tools/verify_shop_errors_native.py](../tools/verify_shop_errors_native.py) | Original F0 wait reset and command47 numeric argument parsing. |
| [tools/verify_shop_purchase_native.py](../tools/verify_shop_purchase_native.py) | Original request builder9919c8; packet-buffer and UI helpers are stubs. |
| [tools/verify_shop_retry_live.py](../tools/verify_shop_retry_live.py) | Controlled native shop-wait regression probe; no inventory/wallet mutation. |
| [tools/verify_shop_sale_native.py](../tools/verify_shop_sale_native.py) | Original request builder99034c; packet-buffer and UI helpers are stubs. |
| [tools/verify_shot_geometry_native.py](../tools/verify_shot_geometry_native.py) | Compare server sight with original ti.exe CanTraceCells and CanTrace. |
| [tools/verify_sight_native.py](../tools/verify_sight_native.py) | Pin original sight packet readers, setter and HUD getter to the client hash. |
| [tools/verify_skill_tree_native.py](../tools/verify_skill_tree_native.py) | Execute AA field reader and C812 writer; isolate managed allocation/UI. |
| [tools/verify_skills_live.py](../tools/verify_skills_live.py) | Read-only verification of original client's skills metadata against XML import. |
| [tools/verify_social_native.py](../tools/verify_social_native.py) | Execute original B502 with name-based self/clan/foreign branch selection. |
| [tools/verify_special_items_native.py](../tools/verify_special_items_native.py) | Original mine GUI caller, deployment reader and known-mine writer. |
| [tools/verify_stage34_portal_integration.py](../tools/verify_stage34_portal_integration.py) | Run the merged portal only in a copied tree, without env files or databases. |
| [tools/verify_stage4_hosted_state.py](../tools/verify_stage4_hosted_state.py) | Read-only post-acceptance health and source parity; never export player rows. |
| [tools/verify_stage7_candidate.py](../tools/verify_stage7_candidate.py) | Prepare locally, then test an owned copy of hosted code with a pinned overlay. |
| [tools/verify_stage7_suite.py](../tools/verify_stage7_suite.py) | Record combined automated checks against an exact frozen runtime revision. |
| [tools/verify_stage9_interfaces.py](../tools/verify_stage9_interfaces.py) | Verify the frozen public candidate in a disposable, isolated local tree. |
| [tools/verify_stage9_interfaces_hosted.py](../tools/verify_stage9_interfaces_hosted.py) | Run the reviewed interface suites on hosted CPU, using disposable saves. |
| [tools/verify_supplied_login.py](../tools/verify_supplied_login.py) | One explicitly authorized TLS account check, with credentials from stdin. |
| [tools/verify_tactical_bots_health_remote.py](../tools/verify_tactical_bots_health_remote.py) | Read-only final health/source/save comparison. Run on the hosted server. |
| [tools/verify_tactical_bots_hosted.py](../tools/verify_tactical_bots_hosted.py) | Disposable ranked-excluded accounts exercise hosted native TLS gameplay. |
| [tools/verify_tactical_marks_native.py](../tools/verify_tactical_marks_native.py) | Execute original B2/06 request writer, B2/07 reader and 200-second expiry. |
| [tools/verify_team_heartbeat_native.py](../tools/verify_team_heartbeat_native.py) | Run the original 3600-frame watchdog and 9E reset; UI/transport stubbed. |
| [tools/verify_team_modes_native.py](../tools/verify_team_modes_native.py) | Original silver.dll mode selectors and BA03 serializer, with UI isolated. |
| [tools/verify_texture_quality_native.py](../tools/verify_texture_quality_native.py) | Execute guarded sampler installer and original native TI setters in x86. |
| [tools/verify_texture_quality_runtime.py](../tools/verify_texture_quality_runtime.py) | Build an owned public-only client and read the hidden launcher probe. |
| [tools/verify_throwable_client_native.py](../tools/verify_throwable_client_native.py) | Execute the released-chain candidate's x86 effects parser/draw callbacks. |
| [tools/verify_town_native.py](../tools/verify_town_native.py) | Original TI TownInfo decoder64a3fc with optional branches absent. |
| [tools/verify_town_visibility_native.py](../tools/verify_town_visibility_native.py) | Original C82D decoder, enabled assignment and map visibility gate. |
| [tools/verify_trade_operations_hosted.py](../tools/verify_trade_operations_hosted.py) | Post-install acceptance with three excluded accounts over production TLS. |
| [tools/verify_transport_native.py](../tools/verify_transport_native.py) | Compare Python cipher state against original unpacked TI x86 routines. |
| [tools/verify_treatment_native.py](../tools/verify_treatment_native.py) | Original missing-HP sum and price multiplication, with human/dog/dead cases. |
| [tools/verify_turn_begin_native.py](../tools/verify_turn_begin_native.py) | Original95e1e0 YourTurn callback; notifications/UI/timer setter isolated. |
| [tools/verify_turn_finish_native.py](../tools/verify_turn_finish_native.py) | Original TurnFinished -> foreign TurnNow, starting with active input. |
| [tools/verify_turn_now_native.py](../tools/verify_turn_now_native.py) | Original wire classifier, TurnNow reader/callback and name-row timer gate. |
| [tools/verify_tutorial_native.py](../tools/verify_tutorial_native.py) | Exact candidate tutorial ground/chat/result and original action ABI proof. |
| [tools/verify_ui_hd_assets_graphical.py](../tools/verify_ui_hd_assets_graphical.py) | Stage and observe selected HD assets only in the existing owned QA pair. |
| [tools/verify_ui_hd_assets_publication.py](../tools/verify_ui_hd_assets_publication.py) | Independent read-only SSH/HTTPS verification of a reviewed HD UI package. |
| [tools/verify_ui_hd_font_loader_native.py](../tools/verify_ui_hd_font_loader_native.py) | Verify real TI font filename Unicode ABI and unique native cache keys. |
| [tools/verify_ui_hd_graphical_evidence.py](../tools/verify_ui_hd_graphical_evidence.py) | Validate saved owned A/B HD-font/icon observations without opening processes. |
| [tools/verify_ui_hd_icon_assets.py](../tools/verify_ui_hd_icon_assets.py) | Verify review-only icon exports without changing native or source assets. |
| [tools/verify_ui_hd_icons_native.py](../tools/verify_ui_hd_icons_native.py) | Execute icon adapter and real native quad/UV math without a game process. |
| [tools/verify_ui_modernization_publication.py](../tools/verify_ui_modernization_publication.py) | Read-only independent SSH/HTTPS verification of the reviewed .12 release. |
| [tools/verify_ui_regressions_state_remote.py](../tools/verify_ui_regressions_state_remote.py) | Read-only hosted verification against the pre-update SQLite backup. |
| [tools/verify_ui_scale_controls_native.py](../tools/verify_ui_scale_controls_native.py) | Run generated scale preference/radio x86 with explicit native function stubs. |
| [tools/verify_ui_scale_graphical.py](../tools/verify_ui_scale_graphical.py) | Owned native UI-scale/portrait QA; no startup on import/help/check-only. |
| [tools/verify_unit_status_native.py](../tools/verify_unit_status_native.py) | Original TUnitStatus.DrawEquipStatus sprite/color selection; rendering stubbed. |
| [tools/verify_upgrade_kit_inventory_native.py](../tools/verify_upgrade_kit_inventory_native.py) | Original IsSimpleUpgradeKit and all six HideUpgradeBoxes UI gates. |
| [tools/verify_upgrade_kit_release_native.py](../tools/verify_upgrade_kit_release_native.py) | Execute final distributed kit visibility bytes in original x86 UI branches. |
| [tools/verify_user_agreement_pages.py](../tools/verify_user_agreement_pages.py) | Read public legal pages and confirm delivery of the accepted agreement. |
| [tools/verify_wager_requests_native.py](../tools/verify_wager_requests_native.py) | Execute pinned silver.dll main-room join/kick/team builders with real writers. |
| [tools/verify_warehouse_capacity_native.py](../tools/verify_warehouse_capacity_native.py) | Verify native warehouse default and private-window capacity selection. |
| [tools/verify_warehouse_native.py](../tools/verify_warehouse_native.py) | Run original63f60c and63ead4 serializers; only managed string cleanup stubbed. |
| [tools/verify_warehouse_queries_native.py](../tools/verify_warehouse_queries_native.py) | Original request builders, empty response writers and wallet wait completion. |
| [tools/verify_warehouse_transfer_native.py](../tools/verify_warehouse_transfer_native.py) | Original992294 array traversal and writers; transport/refcount/UI isolated. |
| [tools/verify_warehouse_ui_arrays_native.py](../tools/verify_warehouse_ui_arrays_native.py) | Execute original single-item UI branches a66645/a667b2 until transfer builder. |
| [tools/verify_weapon_consume_native.py](../tools/verify_weapon_consume_native.py) | Execute native consume attribute stores; XML lookup/conversion isolated. |
| [tools/verify_weapon_damage_native.py](../tools/verify_weapon_damage_native.py) | Original XML patk stores and base damage interval; no simulated numeric math. |
| [tools/verify_weapon_effects_native.py](../tools/verify_weapon_effects_native.py) | Original ammo metadata stores and ability27 writer; rendering is not emulated. |
| [tools/verify_weapon_range_native.py](../tools/verify_weapon_range_native.py) | Execute original weapon XML stores, range damage and accuracy in silver.dll. |
| [tools/verify_weapon_skill_native.py](../tools/verify_weapon_skill_native.py) | Native weapon-type skill selection and skill-dependent damage, isolated from UI. |
| [tools/verify_weapon_swap_native.py](../tools/verify_weapon_swap_native.py) | Original8b72c8 weapon-swap writer; transport flush/UI helpers isolated. |
| [tools/verify_weight_native.py](../tools/verify_weight_native.py) | Execute original weight sum, overload thresholds and 4E serialization/model writes. |
| [tools/verify_world_catalog_native.py](../tools/verify_world_catalog_native.py) | Execute original zones XML loader, B9 receiver and TownInfo consumers. |
| [tools/verify_world_completion_native.py](../tools/verify_world_completion_native.py) | Verify the approved world XML and player standings against published F8. |
| [tools/window_compat.py](../tools/window_compat.py) | Expose the legacy Delphi game form as an application window. |

## tests/

| Файл | Назначение из docstring |
| --- | --- |
| [tests/test_abilities.py](../tests/test_abilities.py) | См. код и вызывающие модули. |
| [tests/test_ability_cast.py](../tests/test_ability_cast.py) | См. код и вызывающие модули. |
| [tests/test_ability_learning.py](../tests/test_ability_learning.py) | См. код и вызывающие модули. |
| [tests/test_ability_progression.py](../tests/test_ability_progression.py) | См. код и вызывающие модули. |
| [tests/test_ability_prices.py](../tests/test_ability_prices.py) | См. код и вызывающие модули. |
| [tests/test_cybernetics.py](../tests/test_cybernetics.py) | См. код и вызывающие модули. |
| [tests/test_ability_protocol.py](../tests/test_ability_protocol.py) | См. код и вызывающие модули. |
| [tests/test_ability_state.py](../tests/test_ability_state.py) | См. код и вызывающие модули. |
| [tests/test_ability_status.py](../tests/test_ability_status.py) | См. код и вызывающие модули. |
| [tests/test_achievement_benefits.py](../tests/test_achievement_benefits.py) | См. код и вызывающие модули. |
| [tests/test_achievement_completed_items.py](../tests/test_achievement_completed_items.py) | См. код и вызывающие модули. |
| [tests/test_achievement_noncity_delivery.py](../tests/test_achievement_noncity_delivery.py) | Pending achievements cannot disconnect a player outside a city. |
| [tests/test_achievements.py](../tests/test_achievements.py) | См. код и вызывающие модули. |
| [tests/test_action_points.py](../tests/test_action_points.py) | См. код и вызывающие модули. |
| [tests/test_alliance_crests.py](../tests/test_alliance_crests.py) | Disposable account/clan fixtures only; no hosted grants or admin accounts. |
| [tests/test_alliance_service.py](../tests/test_alliance_service.py) | Native requests on actual account/clan stores; no hosted account fixtures. |
| [tests/test_alliances.py](../tests/test_alliances.py) | Real local account/clan stores, transaction races and manual alliance costs. |
| [tests/test_appearance.py](../tests/test_appearance.py) | См. код и вызывающие модули. |
| [tests/test_arena.py](../tests/test_arena.py) | См. код и вызывающие модули. |
| [tests/test_arena_fog_validation.py](../tests/test_arena_fog_validation.py) | См. код и вызывающие модули. |
| [tests/test_arena_gears.py](../tests/test_arena_gears.py) | См. код и вызывающие модули. |
| [tests/test_arena_map.py](../tests/test_arena_map.py) | См. код и вызывающие модули. |
| [tests/test_arena_rooms.py](../tests/test_arena_rooms.py) | См. код и вызывающие модули. |
| [tests/test_arena_roster.py](../tests/test_arena_roster.py) | См. код и вызывающие модули. |
| [tests/test_arena_service.py](../tests/test_arena_service.py) | См. код и вызывающие модули. |
| [tests/test_arena_surroundings.py](../tests/test_arena_surroundings.py) | Decorative resources are shared but never become authoritative game cells. |
| [tests/test_armor_damage.py](../tests/test_armor_damage.py) | См. код и вызывающие модули. |
| [tests/test_armor_display.py](../tests/test_armor_display.py) | См. код и вызывающие модули. |
| [tests/test_armor_equipment.py](../tests/test_armor_equipment.py) | См. код и вызывающие модули. |
| [tests/test_armor_models.py](../tests/test_armor_models.py) | См. код и вызывающие модули. |
| [tests/test_assault_arena.py](../tests/test_assault_arena.py) | Eight separate accounts, original maps and journaled server decisions. |
| [tests/test_assault_interface_integration.py](../tests/test_assault_interface_integration.py) | Authoritative owned-slot HTTP and original clan badge projection. |
| [tests/test_assault_location_admission.py](../tests/test_assault_location_admission.py) | Territory bands must allow admitted assaults without opening city arenas. |
| [tests/test_assault_public.py](../tests/test_assault_public.py) | См. код и вызывающие модули. |
| [tests/test_auth2.py](../tests/test_auth2.py) | См. код и вызывающие модули. |
| [tests/test_avatars.py](../tests/test_avatars.py) | Real SQLite owners, durable free choices, native resources and gate checks. |
| [tests/test_backup_tools_deployment.py](../tests/test_backup_tools_deployment.py) | Backup deployment safety on temporary operational files, no host or DB access. |
| [tests/test_balance_editor.py](../tests/test_balance_editor.py) | См. код и вызывающие модули. |
| [tests/test_bank_economy.py](../tests/test_bank_economy.py) | См. код и вызывающие модули. |
| [tests/test_bank_gameplay.py](../tests/test_bank_gameplay.py) | См. код и вызывающие модули. |
| [tests/test_bank_gateway.py](../tests/test_bank_gateway.py) | См. код и вызывающие модули. |
| [tests/test_bank_operations.py](../tests/test_bank_operations.py) | Bank pipeline integration using inspected hosted runtime and real SQLite. |
| [tests/test_base_fund_completion.py](../tests/test_base_fund_completion.py) | Real shared fund debits, accepted receipts, winner payouts and safe refunds. |
| [tests/test_battle_actor_fixture.py](../tests/test_battle_actor_fixture.py) | См. код и вызывающие модули. |
| [tests/test_battle_core.py](../tests/test_battle_core.py) | См. код и вызывающие модули. |
| [tests/test_battle_crash_recovery.py](../tests/test_battle_crash_recovery.py) | Real gameplay transactions and process exits at the commit boundaries. |
| [tests/test_battle_doors.py](../tests/test_battle_doors.py) | См. код и вызывающие модули. |
| [tests/test_battle_events.py](../tests/test_battle_events.py) | См. код и вызывающие модули. |
| [tests/test_battle_exchange.py](../tests/test_battle_exchange.py) | См. код и вызывающие модули. |
| [tests/test_battle_failure_isolation.py](../tests/test_battle_failure_isolation.py) | Real combat, durable settlement retries and independent shared matches. |
| [tests/test_battle_finish.py](../tests/test_battle_finish.py) | См. код и вызывающие модули. |
| [tests/test_battle_ground.py](../tests/test_battle_ground.py) | См. код и вызывающие модули. |
| [tests/test_battle_healing.py](../tests/test_battle_healing.py) | См. код и вызывающие модули. |
| [tests/test_battle_item_effects.py](../tests/test_battle_item_effects.py) | Common authoritative field, account-local CAS, TTL and native packet effects. |
| [tests/test_battle_item_visuals.py](../tests/test_battle_item_visuals.py) | Recipient-private F7/v1 presentation, server TTL and deterministic bounds. |
| [tests/test_battle_loaded.py](../tests/test_battle_loaded.py) | См. код и вызывающие модули. |
| [tests/test_battle_loot.py](../tests/test_battle_loot.py) | См. код и вызывающие модули. |
| [tests/test_battle_members.py](../tests/test_battle_members.py) | См. код и вызывающие модули. |
| [tests/test_battle_move.py](../tests/test_battle_move.py) | См. код и вызывающие модули. |
| [tests/test_battle_position.py](../tests/test_battle_position.py) | См. код и вызывающие модули. |
| [tests/test_battle_recovery.py](../tests/test_battle_recovery.py) | См. код и вызывающие модули. |
| [tests/test_battle_roster_fixture.py](../tests/test_battle_roster_fixture.py) | См. код и вызывающие модули. |
| [tests/test_battle_screen_fixes.py](../tests/test_battle_screen_fixes.py) | Screenshot regressions: native-safe bot owners, initial doors, late EndTurn. |
| [tests/test_battle_soldier.py](../tests/test_battle_soldier.py) | См. код и вызывающие модули. |
| [tests/test_battle_state.py](../tests/test_battle_state.py) | См. код и вызывающие модули. |
| [tests/test_battle_turn.py](../tests/test_battle_turn.py) | См. код и вызывающие модули. |
| [tests/test_battle_turn_regressions.py](../tests/test_battle_turn_regressions.py) | Human/dog visibility under bot actions; eliminated accounts spectate. |
| [tests/test_battle_weapon_regressions.py](../tests/test_battle_weapon_regressions.py) | См. код и вызывающие модули. |
| [tests/test_bot_credit_rewards.py](../tests/test_bot_credit_rewards.py) | Bot credit rates, persisted settlements and shared authoritative activity. |
| [tests/test_bot_finishing.py](../tests/test_bot_finishing.py) | Committed combat decisions: finish weak targets, replan misses, retain cover. |
| [tests/test_capture_shared_mines_recovery.py](../tests/test_capture_shared_mines_recovery.py) | Operator capture wrapper tests: no SSH, no real credentials or plaintext disk. |
| [tests/test_character_create.py](../tests/test_character_create.py) | См. код и вызывающие модули. |
| [tests/test_character_preview.py](../tests/test_character_preview.py) | См. код и вызывающие модули. |
| [tests/test_character_record.py](../tests/test_character_record.py) | См. код и вызывающие модули. |
| [tests/test_character_select.py](../tests/test_character_select.py) | См. код и вызывающие модули. |
| [tests/test_character_slots.py](../tests/test_character_slots.py) | Legacy save preservation, five-slot isolation and native selection TCP. |
| [tests/test_character_store.py](../tests/test_character_store.py) | См. код и вызывающие модули. |
| [tests/test_cities.py](../tests/test_cities.py) | См. код и вызывающие модули. |
| [tests/test_city_catalogs.py](../tests/test_city_catalogs.py) | См. код и вызывающие модули. |
| [tests/test_city_ground_brushes.py](../tests/test_city_ground_brushes.py) | Native ground bytes must match the selected city's published resources. |
| [tests/test_city_inventory.py](../tests/test_city_inventory.py) | См. код и вызывающие модули. |
| [tests/test_city_operations.py](../tests/test_city_operations.py) | Portal actions join real public helpers, scene locks, receipts and sockets. |
| [tests/test_city_scenery.py](../tests/test_city_scenery.py) | См. код и вызывающие модули. |
| [tests/test_city_services.py](../tests/test_city_services.py) | См. код и вызывающие модули. |
| [tests/test_city_services_integration.py](../tests/test_city_services_integration.py) | Services V2 exercises the live city gate, routes, rollback and private tick. |
| [tests/test_city_session.py](../tests/test_city_session.py) | См. код и вызывающие модули. |
| [tests/test_clan_benefits.py](../tests/test_clan_benefits.py) | См. код и вызывающие модули. |
| [tests/test_clan_benefits_integration.py](../tests/test_clan_benefits_integration.py) | Shared transaction integration; temporary databases, no hosted/GUI claim. |
| [tests/test_clan_crest_gateway.py](../tests/test_clan_crest_gateway.py) | См. код и вызывающие модули. |
| [tests/test_clan_crests.py](../tests/test_clan_crests.py) | См. код и вызывающие модули. |
| [tests/test_clan_gameplay.py](../tests/test_clan_gameplay.py) | См. код и вызывающие модули. |
| [tests/test_clan_prize_public_catalog.py](../tests/test_clan_prize_public_catalog.py) | Pending clan prizes must use the shipped catalogue and remain owner isolated. |
| [tests/test_clan_rating_crests.py](../tests/test_clan_rating_crests.py) | Stored clan/alliance image IDs share the classic original rating transport. |
| [tests/test_clan_ratings.py](../tests/test_clan_ratings.py) | См. код и вызывающие модули. |
| [tests/test_clan_warfare_candidate.py](../tests/test_clan_warfare_candidate.py) | См. код и вызывающие модули. |
| [tests/test_clan_warfare_deployment.py](../tests/test_clan_warfare_deployment.py) | См. код и вызывающие модули. |
| [tests/test_clan_warfare_protocol.py](../tests/test_clan_warfare_protocol.py) | Boundaries for original Silver ABI; native execution has a separate tool. |
| [tests/test_clans.py](../tests/test_clans.py) | См. код и вызывающие модули. |
| [tests/test_client_battle_background.py](../tests/test_client_battle_background.py) | Original x86 native enqueue, focus gate, pause gate and callback tick. |
| [tests/test_client_battle_loot.py](../tests/test_client_battle_loot.py) | См. код и вызывающие модули. |
| [tests/test_client_russian_encoding.py](../tests/test_client_russian_encoding.py) | См. код и вызывающие модули. |
| [tests/test_client_upgrade_kit.py](../tests/test_client_upgrade_kit.py) | См. код и вызывающие модули. |
| [tests/test_combat.py](../tests/test_combat.py) | См. код и вызывающие модули. |
| [tests/test_combat_sight_scatter.py](../tests/test_combat_sight_scatter.py) | Manual p39/p63-64 combat state, native projection and crash recovery. |
| [tests/test_completion.py](../tests/test_completion.py) | См. код и вызывающие модули. |
| [tests/test_contest_maps.py](../tests/test_contest_maps.py) | См. код и вызывающие модули. |
| [tests/test_contract_scene.py](../tests/test_contract_scene.py) | Real saved account selections, frozen policies and native PvE packets. |
| [tests/test_contract_world_namespace.py](../tests/test_contract_world_namespace.py) | Local-only contracts retain marker IDs across public world extension. |
| [tests/test_contract_world_scene_compat.py](../tests/test_contract_world_scene_compat.py) | Local-only contract map compatibility, excluded from public hosted rollout. |
| [tests/test_contracts_chat_native.py](../tests/test_contracts_chat_native.py) | Run the pinned native chat tab dispatcher with scoped UI/string stubs. |
| [tests/test_contracts_city_assets.py](../tests/test_contracts_city_assets.py) | Bounded tests for native state/slice packing and the approved source guard. |
| [tests/test_contracts_city_native.py](../tests/test_contracts_city_native.py) | Execute the actual city extension x86 with scoped native API sentinels. |
| [tests/test_contracts_combat.py](../tests/test_contracts_combat.py) | Disposable registered accounts and native protocol checks, not GUI acceptance. |
| [tests/test_contracts_local_tcp.py](../tests/test_contracts_local_tcp.py) | Authenticated loopback TCP coverage; this does not validate graphical clients. |
| [tests/test_contracts_map_view_native.py](../tests/test_contracts_map_view_native.py) | Pinned original x86 map-mode transition, without clients or sockets. |
| [tests/test_contracts_native_research.py](../tests/test_contracts_native_research.py) | Offline evidence for future native Contracts integration, not gameplay tests. |
| [tests/test_contracts_service.py](../tests/test_contracts_service.py) | Opt-in routing and private command checks on disposable account data. |
| [tests/test_credits_only.py](../tests/test_credits_only.py) | См. код и вызывающие модули. |
| [tests/test_crystal_quote_history.py](../tests/test_crystal_quote_history.py) | См. код и вызывающие модули. |
| [tests/test_detroit_wager_maps.py](../tests/test_detroit_wager_maps.py) | Detroit production checks using temporary saved accounts and native packets. |
| [tests/test_dog_abilities.py](../tests/test_dog_abilities.py) | См. код и вызывающие модули. |
| [tests/test_durability.py](../tests/test_durability.py) | См. код и вызывающие модули. |
| [tests/test_economy_antifarm.py](../tests/test_economy_antifarm.py) | Account-pair progression limits in the real settlement transaction. |
| [tests/test_economy_runtime.py](../tests/test_economy_runtime.py) | См. код и вызывающие модули. |
| [tests/test_english_localization.py](../tests/test_english_localization.py) | См. код и вызывающие модули. |
| [tests/test_enhancement.py](../tests/test_enhancement.py) | См. код и вызывающие модули. |
| [tests/test_enhancement_limits.py](../tests/test_enhancement_limits.py) | См. код и вызывающие модули. |
| [tests/test_equipment.py](../tests/test_equipment.py) | См. код и вызывающие модули. |
| [tests/test_equipment_batch.py](../tests/test_equipment_batch.py) | См. код и вызывающие модули. |
| [tests/test_equipment_batch_client.py](../tests/test_equipment_batch_client.py) | См. код и вызывающие модули. |
| [tests/test_equipment_bonuses.py](../tests/test_equipment_bonuses.py) | См. код и вызывающие модули. |
| [tests/test_equipment_descriptions.py](../tests/test_equipment_descriptions.py) | См. код и вызывающие модули. |
| [tests/test_equipment_templates.py](../tests/test_equipment_templates.py) | См. код и вызывающие модули. |
| [tests/test_floor_fire.py](../tests/test_floor_fire.py) | См. код и вызывающие модули. |
| [tests/test_forest_encounters.py](../tests/test_forest_encounters.py) | См. код и вызывающие модули. |
| [tests/test_game_operations.py](../tests/test_game_operations.py) | См. код и вызывающие модули. |
| [tests/test_game_tls.py](../tests/test_game_tls.py) | TLS uses the actual shared TCP/account backend and nonproduction certificates. |
| [tests/test_game_tls_deploy.py](../tests/test_game_tls_deploy.py) | Isolated rollout/renewal guards; no real SSH, systemd, firewall or player saves. |
| [tests/test_game_tls_download_metadata.py](../tests/test_game_tls_download_metadata.py) | Publication guards and private backup ordering without running PostgreSQL. |
| [tests/test_gameplay_deployment.py](../tests/test_gameplay_deployment.py) | Game deployment remains code-only and guards hosted source/data boundaries. |
| [tests/test_global_map_assets.py](../tests/test_global_map_assets.py) | Meaningful asset identity, authoritative geometry and viewport regressions. |
| [tests/test_global_map_client.py](../tests/test_global_map_client.py) | The checked native map extension is presentation-only and SHA guarded. |
| [tests/test_ground_loot.py](../tests/test_ground_loot.py) | Shared ground transfers, combat death and fog regression coverage. |
| [tests/test_health_protocol.py](../tests/test_health_protocol.py) | См. код и вызывающие модули. |
| [tests/test_hire.py](../tests/test_hire.py) | См. код и вызывающие модули. |
| [tests/test_hiring.py](../tests/test_hiring.py) | См. код и вызывающие модули. |
| [tests/test_hosted_clan_warfare.py](../tests/test_hosted_clan_warfare.py) | См. код и вызывающие модули. |
| [tests/test_hosted_completion_probes.py](../tests/test_hosted_completion_probes.py) | Validate public evidence readers and no-network gates, never touch hosting. |
| [tests/test_hosted_economy_verifier.py](../tests/test_hosted_economy_verifier.py) | Safety/negative checks for the optional production economy acceptance tool. |
| [tests/test_hosted_mines_expiry_qa.py](../tests/test_hosted_mines_expiry_qa.py) | Local-only control/receipt/service guards for genuine hosted expiry QA. |
| [tests/test_hosted_stage9_graphical_qa.py](../tests/test_hosted_stage9_graphical_qa.py) | Offline adapter guards; no GUI, Frida attach, production DB or game sockets. |
| [tests/test_hosted_stage9_graphical_qa_revision2.py](../tests/test_hosted_stage9_graphical_qa_revision2.py) | Offline adapter guards; no GUI, Frida attach, production DB or game sockets. |
| [tests/test_hosted_stage9_graphical_qa_revision3.py](../tests/test_hosted_stage9_graphical_qa_revision3.py) | Offline adapter guards; no GUI, Frida attach, production DB or game sockets. |
| [tests/test_hosted_surroundings_asset_contract.py](../tests/test_hosted_surroundings_asset_contract.py) | Published-byte validation fixtures; no network, accounts or native process. |
| [tests/test_hosted_world_travel.py](../tests/test_hosted_world_travel.py) | Offline QA control-flow tests: no sockets, credentials or hosting queries. |
| [tests/test_item_action.py](../tests/test_item_action.py) | См. код и вызывающие модули. |
| [tests/test_item_batch.py](../tests/test_item_batch.py) | См. код и вызывающие модули. |
| [tests/test_item_list.py](../tests/test_item_list.py) | См. код и вызывающие модули. |
| [tests/test_item_stacking.py](../tests/test_item_stacking.py) | См. код и вызывающие модули. |
| [tests/test_known_mines.py](../tests/test_known_mines.py) | См. код и вызывающие модули. |
| [tests/test_launcher_014_publication.py](../tests/test_launcher_014_publication.py) | Local publication safeguards; never connect to production. |
| [tests/test_launcher_archive.py](../tests/test_launcher_archive.py) | См. код и вызывающие модули. |
| [tests/test_launcher_self_update_publication.py](../tests/test_launcher_self_update_publication.py) | Isolated launcher publication/recovery checks; never contact the hosted server. |
| [tests/test_legacy_idle_mine_startup.py](../tests/test_legacy_idle_mine_startup.py) | Actual runtime startup with synthetic idle Mine13 saves, no network/data copy. |
| [tests/test_legacy_lobbies_publication.py](../tests/test_legacy_lobbies_publication.py) | Scoped release guards; synthetic fixtures do not count as gameplay QA. |
| [tests/test_legacy_lobby_city_deployment_guard.py](../tests/test_legacy_lobby_city_deployment_guard.py) | Narrow maintenance policy against real SQLite state and frozen sources. |
| [tests/test_legacy_server_list_observer.py](../tests/test_legacy_server_list_observer.py) | Offline observer validation; these tests never open a hosted connection. |
| [tests/test_legacy_server_status.py](../tests/test_legacy_server_status.py) | Native list06 reports live game accounts and explicit backend availability. |
| [tests/test_level_progression.py](../tests/test_level_progression.py) | См. код и вызывающие модули. |
| [tests/test_loader_evidence.py](../tests/test_loader_evidence.py) | Independent checks on the captured initializer failure and recovery evidence. |
| [tests/test_login.py](../tests/test_login.py) | См. код и вызывающие модули. |
| [tests/test_login_economy_boundary.py](../tests/test_login_economy_boundary.py) | A native empty selection screen grants no economy state or lost wallet. |
| [tests/test_mail.py](../tests/test_mail.py) | См. код и вызывающие модули. |
| [tests/test_mail_protocol.py](../tests/test_mail_protocol.py) | Native mail shapes, distinct string encodings and hostile frame rejection. |
| [tests/test_mail_service.py](../tests/test_mail_service.py) | См. код и вызывающие модули. |
| [tests/test_mail_transport.py](../tests/test_mail_transport.py) | Original mail packets over two actual encrypted TCP account sessions. |
| [tests/test_map_generation.py](../tests/test_map_generation.py) | См. код и вызывающие модули. |
| [tests/test_market_operations.py](../tests/test_market_operations.py) | Market registry, legacy receipts, rollback and concurrent-owner integration. |
| [tests/test_matchmaking.py](../tests/test_matchmaking.py) | См. код и вызывающие модули. |
| [tests/test_menu_interface_publish_safety.py](../tests/test_menu_interface_publish_safety.py) | Exercise UI publication failures against isolated files, never the VPS. |
| [tests/test_menu_interface_release.py](../tests/test_menu_interface_release.py) | UI releases must preserve gameplay records and reject unsafe/stale packages. |
| [tests/test_menu_native_semantics.py](../tests/test_menu_native_semantics.py) | Execute presentation thunks with native ABI sentinels, without game/auth IO. |
| [tests/test_menu_qa_guards.py](../tests/test_menu_qa_guards.py) | Reject altered native/auth modules and personal state in menu graphical QA. |
| [tests/test_mine_claims_and_tax.py](../tests/test_mine_claims_and_tax.py) | См. код и вызывающие модули. |
| [tests/test_mine_requests.py](../tests/test_mine_requests.py) | Queue/membership authority over ordinary disposable character saves. |
| [tests/test_mine_rounds.py](../tests/test_mine_rounds.py) | См. код и вызывающие модули. |
| [tests/test_mine_scene_fixture.py](../tests/test_mine_scene_fixture.py) | См. код и вызывающие модули. |
| [tests/test_miner_abilities.py](../tests/test_miner_abilities.py) | См. код и вызывающие модули. |
| [tests/test_miners.py](../tests/test_miners.py) | См. код и вызывающие модули. |
| [tests/test_miners_town_shop_protocol.py](../tests/test_miners_town_shop_protocol.py) | Exact hosted catalogue candidate over encrypted native socket frames. |
| [tests/test_mining.py](../tests/test_mining.py) | См. код и вызывающие модули. |
| [tests/test_mining_hunter.py](../tests/test_mining_hunter.py) | Mine hunters exercise real turn, movement and combat authority. |
| [tests/test_mining_rating_menu.py](../tests/test_mining_rating_menu.py) | Opening global ratings must not require or enter a mine checkpoint. |
| [tests/test_mode1.py](../tests/test_mode1.py) | См. код и вызывающие модули. |
| [tests/test_moderate_prison.py](../tests/test_moderate_prison.py) | Operator CLI uses actual saved character aliases and atomic prison rules. |
| [tests/test_movement_contact.py](../tests/test_movement_contact.py) | См. код и вызывающие модули. |
| [tests/test_multi_account.py](../tests/test_multi_account.py) | Two real TCP clients, including shared-IP/reordered mode1 and account isolation. |
| [tests/test_native_arena_group_rows.py](../tests/test_native_arena_group_rows.py) | BA02 layout read by actual native Players/Soldiers columns and status names. |
| [tests/test_native_team_lobby_list.py](../tests/test_native_team_lobby_list.py) | Shared native main-table lobbies, account admission and unchanged saves. |
| [tests/test_native_wager_lobby_captions.py](../tests/test_native_wager_lobby_captions.py) | Main native Team/Wall wager rows include live occupancy and countdown state. |
| [tests/test_night_vision_state.py](../tests/test_night_vision_state.py) | Authoritative owner projection, turn expiry and reconnect for F9/v1. |
| [tests/test_nvg_client_native.py](../tests/test_nvg_client_native.py) | Native regressions for safe zero-AP NVG deactivation and F9 state. |
| [tests/test_offsite_backup_windows.py](../tests/test_offsite_backup_windows.py) | Recovery verification/DPAPI/retention tests using synthetic public fixtures only. |
| [tests/test_operate_shared_mines_maintenance.py](../tests/test_operate_shared_mines_maintenance.py) | Operator proof routing only: no SSH, firewall, server or real socket binding. |
| [tests/test_original_shop_prices.py](../tests/test_original_shop_prices.py) | См. код и вызывающие модули. |
| [tests/test_outpost_equipment_copy.py](../tests/test_outpost_equipment_copy.py) | Two saved owners, empty native battle copies and real persistent CAS. |
| [tests/test_owned_pets.py](../tests/test_owned_pets.py) | См. код и вызывающие модули. |
| [tests/test_party_travel.py](../tests/test_party_travel.py) | См. код и вызывающие модули. |
| [tests/test_passive_stats.py](../tests/test_passive_stats.py) | См. код и вызывающие модули. |
| [tests/test_pet_info.py](../tests/test_pet_info.py) | См. код и вызывающие модули. |
| [tests/test_pet_state.py](../tests/test_pet_state.py) | См. код и вызывающие модули. |
| [tests/test_player_auction.py](../tests/test_player_auction.py) | См. код и вызывающие модули. |
| [tests/test_player_statistics.py](../tests/test_player_statistics.py) | См. код и вызывающие модули. |
| [tests/test_player_top100.py](../tests/test_player_top100.py) | См. код и вызывающие модули. |
| [tests/test_player_trade.py](../tests/test_player_trade.py) | См. код и вызывающие модули. |
| [tests/test_player_trade_transport.py](../tests/test_player_trade_transport.py) | Real independent TCP accounts through the production session dispatcher. |
| [tests/test_portal_backup.py](../tests/test_portal_backup.py) | Portal backup publication and restore checks without PostgreSQL or network. |
| [tests/test_post_battle_achievement_delivery.py](../tests/test_post_battle_achievement_delivery.py) | City delivery after retained result bookkeeping, including real TCP frames. |
| [tests/test_post_battle_treatment.py](../tests/test_post_battle_treatment.py) | См. код и вызывающие модули. |
| [tests/test_premium_account.py](../tests/test_premium_account.py) | См. код и вызывающие модули. |
| [tests/test_prepare_contracts_city_local.py](../tests/test_prepare_contracts_city_local.py) | См. код и вызывающие модули. |
| [tests/test_prepare_contracts_local.py](../tests/test_prepare_contracts_local.py) | См. код и вызывающие модули. |
| [tests/test_presence.py](../tests/test_presence.py) | См. код и вызывающие модули. |
| [tests/test_private_market.py](../tests/test_private_market.py) | См. код и вызывающие модули. |
| [tests/test_private_market_refresh.py](../tests/test_private_market_refresh.py) | A native locally closed window must stay closed during an asset poll. |
| [tests/test_public_profile.py](../tests/test_public_profile.py) | См. код и вызывающие модули. |
| [tests/test_public_runtime_regression_controls.py](../tests/test_public_runtime_regression_controls.py) | Regression runner boundaries: no SSH, hosted saves or real credentials. |
| [tests/test_publish_battle_icon_centering_remote.py](../tests/test_publish_battle_icon_centering_remote.py) | См. код и вызывающие модули. |
| [tests/test_publish_battle_ui_hd_remote.py](../tests/test_publish_battle_ui_hd_remote.py) | См. код и вызывающие модули. |
| [tests/test_publish_gameplay_nvg_client.py](../tests/test_publish_gameplay_nvg_client.py) | Execute the reviewed SSH publisher transaction only in disposable files. |
| [tests/test_publish_gameplay_sc_client.py](../tests/test_publish_gameplay_sc_client.py) | См. код и вызывающие модули. |
| [tests/test_publish_global_map_remote.py](../tests/test_publish_global_map_remote.py) | Publication mechanics against real reviewed bytes, with a simulated host. |
| [tests/test_publish_mine_path_entry_remote.py](../tests/test_publish_mine_path_entry_remote.py) | См. код и вызывающие модули. |
| [tests/test_publish_world_completion_client.py](../tests/test_publish_world_completion_client.py) | См. код и вызывающие модули. |
| [tests/test_pve_contracts.py](../tests/test_pve_contracts.py) | См. код и вызывающие модули. |
| [tests/test_quest_ack.py](../tests/test_quest_ack.py) | См. код и вызывающие модули. |
| [tests/test_ranked.py](../tests/test_ranked.py) | См. код и вызывающие модули. |
| [tests/test_ranked_achievements.py](../tests/test_ranked_achievements.py) | Achievements use the actual accepted rating transaction, never previews. |
| [tests/test_ranked_requeue.py](../tests/test_ranked_requeue.py) | A repeated TrueSkill Continue updates the queued squad instead of dropping it. |
| [tests/test_ranked_squads.py](../tests/test_ranked_squads.py) | Original C6 packets with two independent human accounts and saved squads. |
| [tests/test_ranks.py](../tests/test_ranks.py) | См. код и вызывающие модули. |
| [tests/test_rating_completion.py](../tests/test_rating_completion.py) | Eight authoritative save owners; independent Wall values and UTC archive. |
| [tests/test_rating_visibility.py](../tests/test_rating_visibility.py) | См. код и вызывающие модули. |
| [tests/test_ratings_public.py](../tests/test_ratings_public.py) | Read-only public rankings use real independent accounts, private hops and locks. |
| [tests/test_recovery_bundle.py](../tests/test_recovery_bundle.py) | Full recovery capture safety against temporary fixtures and fake commands. |
| [tests/test_rental.py](../tests/test_rental.py) | См. код и вызывающие модули. |
| [tests/test_repair_kit_stacking.py](../tests/test_repair_kit_stacking.py) | Repair Kits 17/18/19 stack when identical; partial use splits one kit off. |
| [tests/test_reservation_launcher.py](../tests/test_reservation_launcher.py) | См. код и вызывающие модули. |
| [tests/test_reservation_texture_codec.py](../tests/test_reservation_texture_codec.py) | Native BMP alpha resources must not become opaque RGBA PNG files. |
| [tests/test_reservation_visuals.py](../tests/test_reservation_visuals.py) | Visual bindings must preserve authoritative gameplay and other cities. |
| [tests/test_reward_policy.py](../tests/test_reward_policy.py) | См. код и вызывающие модули. |
| [tests/test_roster_progression.py](../tests/test_roster_progression.py) | См. код и вызывающие модули. |
| [tests/test_run_launcher_update_publication.py](../tests/test_run_launcher_update_publication.py) | Version-aware publication packaging checks with all network calls mocked. |
| [tests/test_sc_auction.py](../tests/test_sc_auction.py) | См. код и вызывающие модули. |
| [tests/test_sc_auction_view.py](../tests/test_sc_auction_view.py) | См. код и вызывающие модули. |
| [tests/test_sc_clear_cart.py](../tests/test_sc_clear_cart.py) | См. код и вызывающие модули. |
| [tests/test_sc_native_adapter.py](../tests/test_sc_native_adapter.py) | См. код и вызывающие модули. |
| [tests/test_sc_ready_pricing.py](../tests/test_sc_ready_pricing.py) | Independent cost equations and authoritative SC transaction boundaries. |
| [tests/test_sc_shop.py](../tests/test_sc_shop.py) | См. код и вызывающие модули. |
| [tests/test_scheduled_backup.py](../tests/test_scheduled_backup.py) | См. код и вызывающие модули. |
| [tests/test_server_deployment.py](../tests/test_server_deployment.py) | Deployment boundary: real sockets and SQLite, no Windows client/hooks. |
| [tests/test_server_list.py](../tests/test_server_list.py) | См. код и вызывающие модули. |
| [tests/test_server_login.py](../tests/test_server_login.py) | См. код и вызывающие модули. |
| [tests/test_service_operations.py](../tests/test_service_operations.py) | Integration against the inspected hosted runtime; see check_game_operations.py. |
| [tests/test_services.py](../tests/test_services.py) | См. код и вызывающие модули. |
| [tests/test_shared_battle_experience.py](../tests/test_shared_battle_experience.py) | Real shared PvP result IDs, earned XP and replay after a process crash. |
| [tests/test_shared_battle_items.py](../tests/test_shared_battle_items.py) | Four-account authoritative actions, TTL, private recon and rollback. |
| [tests/test_shared_config.py](../tests/test_shared_config.py) | См. код и вызывающие модули. |
| [tests/test_shared_config_delivery.py](../tests/test_shared_config_delivery.py) | Check encrypted phase ordering and reject an unexpected config reply. |
| [tests/test_shared_equipment_batch.py](../tests/test_shared_equipment_batch.py) | См. код и вызывающие модули. |
| [tests/test_shared_mine_arena.py](../tests/test_shared_mine_arena.py) | Native checkpoint requests against a real journaled hub and disposable DB. |
| [tests/test_shared_mine_disconnect.py](../tests/test_shared_mine_disconnect.py) | Real journaled three-account mining retirement and failed isolation paths. |
| [tests/test_shared_mines_deployment_revision.py](../tests/test_shared_mines_deployment_revision.py) | Local revision manifest checks; no SSH or deployment execution. |
| [tests/test_shared_mines_maintenance.py](../tests/test_shared_mines_maintenance.py) | Local operational guard checks: real SQLite, source hashes and snapshot codec. |
| [tests/test_shared_mines_qa.py](../tests/test_shared_mines_qa.py) | Independent, local-only safeguards for shared-mines acceptance tooling. |
| [tests/test_shared_mines_route.py](../tests/test_shared_mines_route.py) | Local-only refusal/collision tests for mining QA route planning. |
| [tests/test_shared_mining_state.py](../tests/test_shared_mining_state.py) | One authoritative mine: live squads, per-owner fog/exits and round locks. |
| [tests/test_shared_special_items.py](../tests/test_shared_special_items.py) | Two SQLite accounts, native shared actions and durable hazard recovery. |
| [tests/test_shared_survival_groups.py](../tests/test_shared_survival_groups.py) | Authoritative free-for-all scenes for three/four distinct saved accounts. |
| [tests/test_shared_team_arena.py](../tests/test_shared_team_arena.py) | См. код и вызывающие модули. |
| [tests/test_shared_tutorial.py](../tests/test_shared_tutorial.py) | См. код и вызывающие модули. |
| [tests/test_shared_wager_arena.py](../tests/test_shared_wager_arena.py) | Real saved accounts share wager scenes, escrow and restart outcomes. |
| [tests/test_shooting_range.py](../tests/test_shooting_range.py) | См. код и вызывающие модули. |
| [tests/test_shop.py](../tests/test_shop.py) | См. код и вызывающие модули. |
| [tests/test_shop_clan_benefits.py](../tests/test_shop_clan_benefits.py) | Actual native shop mutations plus clan benefits; isolated SQLite, no GUI claim. |
| [tests/test_shop_completion.py](../tests/test_shop_completion.py) | Accepted transactions against scoped published-source shop candidates. |
| [tests/test_shop_errors.py](../tests/test_shop_errors.py) | См. код и вызывающие модули. |
| [tests/test_shop_purchase.py](../tests/test_shop_purchase.py) | См. код и вызывающие модули. |
| [tests/test_skills_fixture.py](../tests/test_skills_fixture.py) | См. код и вызывающие модули. |
| [tests/test_social_completion.py](../tests/test_social_completion.py) | Authenticated social boundaries, real stores, shared transactions and clocks. |
| [tests/test_special_items.py](../tests/test_special_items.py) | Authoritative shared-account supplies, delayed damage and save recovery. |
| [tests/test_squad.py](../tests/test_squad.py) | См. код и вызывающие модули. |
| [tests/test_stage2_admission_capacity.py](../tests/test_stage2_admission_capacity.py) | Admission work budgets and atomic carried-inventory limits. |
| [tests/test_stage4_deployment.py](../tests/test_stage4_deployment.py) | Real temporary files/SQLite; no SSH, services, or production paths. |
| [tests/test_stage7_hosted_qa.py](../tests/test_stage7_hosted_qa.py) | См. код и вызывающие модули. |
| [tests/test_starting_funds.py](../tests/test_starting_funds.py) | Registration -> authenticated TCP provisioning with disposable player data. |
| [tests/test_steam_package.py](../tests/test_steam_package.py) | См. код и вызывающие модули. |
| [tests/test_survival_multiplayer_queue.py](../tests/test_survival_multiplayer_queue.py) | Authoritative Survival admission for 2-4 independent queued identities. |
| [tests/test_survival_scene.py](../tests/test_survival_scene.py) | См. код и вызывающие модули. |
| [tests/test_survival_service.py](../tests/test_survival_service.py) | См. код и вызывающие модули. |
| [tests/test_system_message.py](../tests/test_system_message.py) | См. код и вызывающие модули. |
| [tests/test_tactical_bot.py](../tests/test_tactical_bot.py) | Behavior checks against real AP, loot, combat and fog services. |
| [tests/test_tactical_marks.py](../tests/test_tactical_marks.py) | См. код и вызывающие модули. |
| [tests/test_team_battles.py](../tests/test_team_battles.py) | См. код и вызывающие модули. |
| [tests/test_team_heartbeat.py](../tests/test_team_heartbeat.py) | Quiet shared battles must reset the original client's frame watchdog. |
| [tests/test_team_lobbies.py](../tests/test_team_lobbies.py) | См. код и вызывающие модули. |
| [tests/test_team_ranked.py](../tests/test_team_ranked.py) | Four persisted accounts through native Team packets and crash checkpoints. |
| [tests/test_team_ratings.py](../tests/test_team_ratings.py) | См. код и вызывающие модули. |
| [tests/test_territories.py](../tests/test_territories.py) | Real SQLite clan/group authority; no hosted or graphical-client claim. |
| [tests/test_town_info.py](../tests/test_town_info.py) | См. код и вызывающие модули. |
| [tests/test_trace.py](../tests/test_trace.py) | См. код и вызывающие модули. |
| [tests/test_trade_window_refresh.py](../tests/test_trade_window_refresh.py) | Actual encrypted city sessions must not receive unsolicited market UI lists. |
| [tests/test_training_arena.py](../tests/test_training_arena.py) | Candidate mixin against the real hub/native actions; no VPS/GUI claim. |
| [tests/test_training_bot.py](../tests/test_training_bot.py) | См. код и вызывающие модули. |
| [tests/test_transport.py](../tests/test_transport.py) | См. код и вызывающие модули. |
| [tests/test_travel_party.py](../tests/test_travel_party.py) | См. код и вызывающие модули. |
| [tests/test_upgrade_kit_stacking.py](../tests/test_upgrade_kit_stacking.py) | Upgrade Kits occupy one warehouse/backpack cell per location as one stack. |
| [tests/test_verify_hosted_gameplay_modes.py](../tests/test_verify_hosted_gameplay_modes.py) | QA tool checks and a real local four-account TLS scenario; no VPS access. |
| [tests/test_verify_published_launcher_update.py](../tests/test_verify_published_launcher_update.py) | Small local checks for the read-only public verification boundary. |
| [tests/test_visibility.py](../tests/test_visibility.py) | См. код и вызывающие модули. |
| [tests/test_visibility_range_cost.py](../tests/test_visibility_range_cost.py) | Range pruning must preserve the frozen pre-fix fog and item semantics. |
| [tests/test_wagers.py](../tests/test_wagers.py) | См. код и вызывающие модули. |
| [tests/test_wall_ranked.py](../tests/test_wall_ranked.py) | Eight independent humans through unchanged native Wall join/ready/attack/exit. |
| [tests/test_wallets.py](../tests/test_wallets.py) | См. код и вызывающие модули. |
| [tests/test_warehouse.py](../tests/test_warehouse.py) | См. код и вызывающие модули. |
| [tests/test_warehouse_completion.py](../tests/test_warehouse_completion.py) | City isolation, legacy preservation and real scoped-consumer transactions. |
| [tests/test_warehouse_errors.py](../tests/test_warehouse_errors.py) | См. код и вызывающие модули. |
| [tests/test_warehouse_queries.py](../tests/test_warehouse_queries.py) | См. код и вызывающие модули. |
| [tests/test_warehouse_store.py](../tests/test_warehouse_store.py) | См. код и вызывающие модули. |
| [tests/test_warehouse_transfer.py](../tests/test_warehouse_transfer.py) | См. код и вызывающие модули. |
| [tests/test_weapon_damage_xml.py](../tests/test_weapon_damage_xml.py) | См. код и вызывающие модули. |
| [tests/test_weapon_effects.py](../tests/test_weapon_effects.py) | См. код и вызывающие модули. |
| [tests/test_weapon_proficiency.py](../tests/test_weapon_proficiency.py) | См. код и вызывающие модули. |
| [tests/test_weapon_range.py](../tests/test_weapon_range.py) | См. код и вызывающие модули. |
| [tests/test_weapon_skill_damage.py](../tests/test_weapon_skill_damage.py) | Combat regressions for class-specific proficiency, not just its helper math. |
| [tests/test_weapons.py](../tests/test_weapons.py) | См. код и вызывающие модули. |
| [tests/test_weather.py](../tests/test_weather.py) | Shared weather, recipient visibility, shelter and checkpoint continuity. |
| [tests/test_weight.py](../tests/test_weight.py) | См. код и вызывающие модули. |
| [tests/test_world_bootstrap.py](../tests/test_world_bootstrap.py) | См. код и вызывающие модули. |
| [tests/test_world_completion.py](../tests/test_world_completion.py) | См. код и вызывающие модули. |
| [tests/test_world_completion_catalog.py](../tests/test_world_completion_catalog.py) | World source preservation, native metadata and bounded geometry checks. |
| [tests/test_world_core_integration.py](../tests/test_world_core_integration.py) | Phase8 pure core checks; no hosted rollout or full client GUI assertion. |
| [tests/test_world_encounters.py](../tests/test_world_encounters.py) | См. код и вызывающие модули. |
| [tests/test_world_profile_rating.py](../tests/test_world_profile_rating.py) | World standings and the clan profile share one signed earned rating. |
| [tests/test_world_reward_integration.py](../tests/test_world_reward_integration.py) | Shared native PvP admission/rewards against actual SQLite/journal authority. |
| [tests/test_world_runtime.py](../tests/test_world_runtime.py) | Authenticated native world requests and SQLite online prison sessions. |
| [tests/wallet_fixture.py](../tests/wallet_fixture.py) | Explicitly funded, pre-existing wallets for tests of paid gameplay features. |

## deploy/

| Файл | Назначение из docstring |
| --- | --- |
| [deploy/backup.py](../deploy/backup.py) | Consistent SQLite backup, without modifying the source or replacing a backup. |
| [deploy/check_connection.py](../deploy/check_connection.py) | Read the original encrypted TIO challenge. Does not authenticate or change saves. |
| [deploy/client_arena_browsing_visible.py](../deploy/client_arena_browsing_visible.py) | Keep actual Team/Wall browse window visible with zero selected fighters. |
| [deploy/client_arena_empty_roster_navigation.py](../deploy/client_arena_empty_roster_navigation.py) | Compose actual Arena mode0 browsing over immutable search-status candidate. |
| [deploy/client_arena_lobby_navigation.py](../deploy/client_arena_lobby_navigation.py) | Keep arena Team/Wall list navigation usable with an empty filtered roster. |
| [deploy/client_arena_lobby_search_status.py](../deploy/client_arena_lobby_search_status.py) | Exact published .2 -> arena navigation plus occupied/search status colours. |
| [deploy/client_avatar_types.py](../deploy/client_avatar_types.py) | Expand the exact published FC whitelist; preserve all other client bytes. |
| [deploy/client_avatars.py](../deploy/client_avatars.py) | FC assignment receiver wrapping the exact published rain release. |
| [deploy/client_battle_background.py](../deploy/client_battle_background.py) | Checked native queue wakeup for the original Windows client. |
| [deploy/client_battle_exchange.py](../deploy/client_battle_exchange.py) | Checked release extension: own-merc exchange opening6E, loose gear and 1AP gate. |
| [deploy/client_battle_items.py](../deploy/client_battle_items.py) | Bounded client extension after the exact phase2 equipment release. |
| [deploy/client_battle_loot.py](../deploy/client_battle_loot.py) | Allow unmarked equipment in the active battle's ground-container UI. |
| [deploy/client_battle_tooltip_scale.py](../deploy/client_battle_tooltip_scale.py) | Correct the battle cursor balloon's existing logical-pixel render scope. |
| [deploy/client_battle_ui_hd.py](../deploy/client_battle_ui_hd.py) | Bounded item/battle icon source-density extension for the reviewed client. |
| [deploy/client_character_onboarding.py](../deploy/client_character_onboarding.py) | Creation-only free editor presentation, layered over the verified v1 transition. |
| [deploy/client_character_onboarding_v1.py](../deploy/client_character_onboarding_v1.py) | Known-build PE extension: server 12/05 -> next character list opens native editor. |
| [deploy/client_contracts_city.py](../deploy/client_contracts_city.py) | Known-build local-only native city controls for cooperative Contracts. |
| [deploy/client_equipment_batch.py](../deploy/client_equipment_batch.py) | Checked client release extension for emulator-only equipment F6/v1. |
| [deploy/client_generated_avatars.py](../deploy/client_generated_avatars.py) | Extend the exact hosted FC avatar reader while preserving every other byte. |
| [deploy/client_global_map.py](../deploy/client_global_map.py) | Checked native full-viewport global-map presentation for release 2026.10.10.4. |
| [deploy/client_global_map_filter.py](../deploy/client_global_map_filter.py) | Map-only GPU mip generation and reversible native sampler state. |
| [deploy/client_global_map_visual.py](../deploy/client_global_map_visual.py) | Scoped native filled-disc removal and label adjustments. |
| [deploy/client_menu_interface.py](../deploy/client_menu_interface.py) | A bounded native presentation patch against the published October 7 client. |
| [deploy/client_mine_hover_scale.py](../deploy/client_mine_hover_scale.py) | Restore physical mouse coordinates only during native deposit hit testing. |
| [deploy/client_mine_path_entry.py](../deploy/client_mine_path_entry.py) | Invalidate native path caches at the actual completed-scene boundary. |
| [deploy/client_portrait_quality.py](../deploy/client_portrait_quality.py) | Pure, SHA-guarded portrait supersampling and native enlarged preview. |
| [deploy/client_rain_weather.py](../deploy/client_rain_weather.py) | Scoped FB rain presentation after the exact published throwable release. |
| [deploy/client_russian_encoding.py](../deploy/client_russian_encoding.py) | Pin the known Russian client's Delphi ANSI conversions to Windows-1251. |
| [deploy/client_sc_auction.py](../deploy/client_sc_auction.py) | Checked F8/v1 SC GUI receiver after the exact phase3 item release. |
| [deploy/client_sc_checkout.py](../deploy/client_sc_checkout.py) | Repair SC payment after Windows rebases Silver away from 0x400000. |
| [deploy/client_screen_resolution_ui.py](../deploy/client_screen_resolution_ui.py) | Pure, SHA-guarded modern resolution presets for the published TI Screen panel. |
| [deploy/client_screen_settings.py](../deploy/client_screen_settings.py) | Guarded native Screen Apply extension; no process or publication side effects. |
| [deploy/client_server_list_freshness.py](../deploy/client_server_list_freshness.py) | Bounded native refresh while the authenticated server-list window is visible. |
| [deploy/client_server_list_status.py](../deploy/client_server_list_status.py) | Legacy native server row: TI-REBORN, availability colours, integer online. |
| [deploy/client_team_lobby_availability.py](../deploy/client_team_lobby_availability.py) | Use any owned fighter for Team/Wall list availability in legacy Silver. |
| [deploy/client_texture_quality.py](../deploy/client_texture_quality.py) | Checked native sampler filtering for the original 0.1.6 client. |
| [deploy/client_throwable_effects.py](../deploy/client_throwable_effects.py) | Animate server-visible F7 cells through original image/sound SDK bridges. |
| [deploy/client_ui_hd_fonts.py](../deploy/client_ui_hd_fonts.py) | Guarded Silver-only Roboto Condensed density adapter for published .12. |
| [deploy/client_ui_hd_icons.py](../deploy/client_ui_hd_icons.py) | Selected classic-A icon density adapter composed after the font adapter. |
| [deploy/client_ui_scale.py](../deploy/client_ui_scale.py) | Pure native UI scaling extension for the published 2026.10.09.11 client. |
| [deploy/client_ui_scale_controls.py](../deploy/client_ui_scale_controls.py) | SHA-guarded Screen scale controls and native client preference persistence. |
| [deploy/client_upgrade_kit.py](../deploy/client_upgrade_kit.py) | Persist the four known Upgrade Kit UI fixes in the distributed silver.dll. |
| [deploy/package_friend_client.py](../deploy/package_friend_client.py) | Package the installed client with a simple launcher and no saved credentials. |
| [deploy/package_server.py](../deploy/package_server.py) | Build a source deployment bundle; never include saves or captured binaries. |
| [deploy/publish_battle_exchange.py](../deploy/publish_battle_exchange.py) | Publish the checked client blob, then atomically switch the launcher manifest. |
| [deploy/publish_menu_interface_update.py](../deploy/publish_menu_interface_update.py) | Publish a prepared UI release and verify its public HTTPS content. |
| [deploy/publish_menu_update.py](../deploy/publish_menu_update.py) | Publish verified menu-only blobs first, then atomically replace the manifest. |
| [deploy/publish_ui_regressions.py](../deploy/publish_ui_regressions.py) | Publish the checked client blob, then atomically switch the launcher manifest. |
| [deploy/publish_upgrade_kit_update.py](../deploy/publish_upgrade_kit_update.py) | Publish the checked client blob, then atomically switch the launcher manifest. |
| [deploy/recovery_bundle.py](../deploy/recovery_bundle.py) | Capture a private, verified platform recovery archive to binary stdout. |
| [deploy/renew_game_tls.py](../deploy/renew_game_tls.py) | Install the domain's game TLS credentials locally and request a safe reload. |
| [deploy/scheduled_backup.py](../deploy/scheduled_backup.py) | Verified SQLite snapshots; expire only this job's dated automatic backups. |
