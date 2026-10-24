# Health Injection and Night Vision Goggles — 24 October 2026

The owner requested original-manual effects, descriptions and shop availability,
and approved prices of **300 credits** for Health Injection and **1800 credits**
for Night Vision Goggles. SC denotes the separate store, not another currency.

## Confirmed issues and changes

Health Injection is existing template **20**, distinct from maximum-health
Injection HP (5012). Its published/server metadata already heals 100 HP and
weighs 100, but its old cost was 10 AP and no shop offered it. The original
manual screenshot specifies 8 AP. The new `config/medical_items.json` is the
shared source for medical healing/AP values used by combat and client export.
Other medical items retain their values. Treatment remains capped at maximum
health and consumes one item after successful validation/persistence.

Night Vision Goggles are existing template **5002**, weight 50, durability
300/300, required level 4. They already existed in the ordinary catalog but
were missing from the separate SC catalog. Activation in a dark battle gives
two additional sight cells and 20 armor, costs 3 AP, and wears the device by
3; subsequent actor generations pay once each. Insufficient AP, daylight or
a missing device disable the effect. Deactivation remains possible at zero
AP. This release preserves that established activation contract and reads the
armor/sight values from the existing policy instead of duplicating constants.

Both stores now offer the two items at the approved credit prices, preserving
the existing town level bands. Reservation's level 1–3 assortment still
excludes the level 4 goggles; eligible mines, cities and bases include them.
Existing offer/lot identities and cart terms are preserved; new identities
are 65020 (ordinary Health Injection), 1020 (premium wire alias), 100020
(SC Health Injection) and 105002 (SC goggles). Gold wire fields remain zero
or use the existing credit alias according to the established protocol.

The client update changes exactly three resources: Health Injection's AP
field in `base/shared config/items.xml` and the two existing NVG text rows in
both language files. NVG text includes armor, dark sight and recurring AP.
The native tooltip already provides weight, level and durability. Ordinary
Health Injection keeps its native “Heals 100 hp” tooltip and now shows 8 AP.
`silver.dll` and launcher **0.1.34** remain unchanged.

## Verification and deployment

Sixteen new regressions cover both stores, credit debit and retry isolation
with two accounts, level bands, insufficient funds, healing boundaries,
foreign-actor refusal, duplicate consumption, optical effects/turn charging,
reconnect, zero-AP deactivation and bounded client changes. A native shared
mine integration test verifies both actions, durability and persistence with
two accounts on one journaled server. Four existing NVG snapshot tests were
added to the portable baseline. The existing Health Injection expectation in
`test_weapon_effects.py` was updated from 10 to the verified 8 AP.

- New tests were red before implementation and green afterwards.
- **611 portable tests pass**, including the new cases; preflight and handoff
  checks pass. One legacy expectation of 10 AP was updated after its failure.
- **61 checks pass on the isolated VPS candidate** using Python 3.11: medical/
  optical scenarios, NVG snapshots, combat, credit economy and shop locations.
- The broader legacy battle-item suite has two unrelated source-checkout
  fixture failures: absent `evidence/battle_item_native.json`, and its old XML
  extension count expects 12 while the checked-in extension XML contains 11.
  Its other 34 cases pass; these failures were not disguised as a clean suite.

The seven runtime/config files were installed after active battles completed.
The guarded deployer created online/cutover SQLite and previous-code/config
backups, verified all 174 tables unchanged at replacement, and restarted the
service. All 32 accounts, protected player tables and configuration remain
preserved; database integrity is OK. No local player data was uploaded or
restored. Client **2026.10.24.2** is published and verified through trusted
HTTPS. Publication independently checked installed runtime hashes and changed
only the three resources; it did not restart the service again.

Server backup:
`/root/tio-before-game-operations-medical-optics-20261024-installed`.
Client backup: `/root/tio-before-medical-optics-client-m8z8widg`.
Detailed operational receipts and QA results remain outside Git.

Players must close the game and reopen the launcher for the corrected client
metadata/text. Automated integration/protocol checks do not constitute
graphical-client acceptance of rendering or gameplay. Rollback restores the
previous code and client manifest only after checking live revision parity;
never restore the older player database as a code rollback. New item
inventories and receipts must be preserved.
