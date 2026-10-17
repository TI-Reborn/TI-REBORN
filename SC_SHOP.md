# SC shop — 2026-09-19

## Current implementation — 2026-10-15

The authoritative store is `tio/shop_completion.py` (exported as SCShopStore).
It uses credits and the ready-equipment policy in `config/shop_completion.json`.
The launch notes below describe the earlier provisional Gold implementation.

Client release **2026.10.15.2** fixes **Pay / Оплатить**, **Clear basket /
Очистить корзину**, catalog prices and basket totals in both native SC views.
Prices and currency sprites use credits. Pay remains visible and requires a
nonempty affordable basket; Clear remains visible and requires a nonempty
basket, independently of the wallet. Payment retains the selected owned fighter.
The clear button reuses the retired Gold payment control. The original
remove writer sends `B4 0A + lot:u32=0`; lot0 is reserved for clearing every
unpurchased row and frozen quote belonging to the authenticated save owner.
The response is the original empty `B4 08` basket with zero totals. Removing a
nonzero lot still decrements one unit. Clear never buys or sells anything and
does not require a selected soldier, sufficient credits, or Gold.

Clear is a city mutation, uses `BEGIN IMMEDIATE`, preserves other accounts,
wallets, inventories, stock and history, and can remove stale basket terms.
The new caption is localized by the dedicated `sccl` key. Client enablement
depends on basket rows, rather than the retired Gold affordability check.
This button is an emulator extension using original native UI/protocol code;
an original mass-clear command was not established by the binary investigation.

The October 14 release left the catalog renderer reading Gold and hid Pay.
Release 15.1 corrected the display at the preferred PE base but left obsolete
HIGHLOW relocations over relative calls and rewritten clear code. Windows
rebasing corrupted these instructions. Release 15.2 restores original relocated
basket loads, removes the unnecessary getters and neutralizes 13 obsolete
relocations. The newer clear refresh is position independent. In the actual PE,
`[AC6078]` aliases `ACFF9C`; these are not independent basket roots. The previous
test's independent pointers were artificial and did not reflect that alias.

The regression now passes B4/08 through both native refresh functions at
`0x400000` and `0x10400000`, applying the real PE relocation table. It executes
the original quantity sum and stock validation, rather than stubbing those
decisions. It reproduces the published 15.1 failure after rebase. Eight candidate
cases cover an AK-47 +10 at 348700 credits with zero, insufficient, exact and
977671 credits. The native selection event, both sets of totals/buttons,
confirmation, Recruit 2 checkout and empty-cart reply execute. GUI drawing,
formatting, object allocation and network boundaries remain bounded stubs;
this is not a graphical client test.

The expanded regression covers all **435 offers / 95 templates**, including
all configured +0/+10/+15/+20/+25 variants and 100-unit supply packs. Each
authoritative basket is passed through the rebased native UI; every price/icon,
insufficient/exact balance, selected-recipient writer, complete server debit,
receipt, enhancement, full durability and emptied basket are checked. The
second account's wallet/cart are preserved. The tested assortment matches a
catalog calculated from the hosted code/config by SHA-256. These exhaustive
checks use a disposable local database; hosted encrypted TCP tests separately
verify actual AK-47 +10 checkout to Recruit 2 and multi-account isolation.

Evidence and deployment reports: `reports/sc-checkout-fix-20261015`, with earlier
server clear coverage in `reports/sc-clear-cart-20261014`. Two public encrypted
TCP clients verify isolation, repeated clearing, no balance/inventory changes
on clear and reconnect persistence. Graphical Windows UI
interaction is not claimed as verified. The corresponding automated tests are
`tests/test_sc_clear_cart.py`.

Implemented in `tio/sc_shop.py`, `tio/protocol/sc_shop.py`, with routing in
`tools/loopback_exchange.py`. The hosted multiplayer server loads this service. The 2026-09-19 launch notes
are historical. Supported and incomplete item effects are listed in
[WEAPON_EFFECTS.md](WEAPON_EFFECTS.md); shop availability is not effect support.

## Recovered protocol

Addresses refer to the installed silver.dll, SHA256
`a73396748ea5c3530157db53592a9f3e04744592c3711f38d40d4877b785de11`.

| Request | Meaning | Response |
| --- | --- | --- |
| B4 04 | Catalog, native writer 656204 | B4 05 |
| B4 06 + lot:u32 + pet:u32 + payment:u32 | Direct purchase, 6560bc; UI 8ee1ec supplies selected pet and payment 2 | ItemList30, AssetCount C8/39, catalog, cart |
| B4 07 | Cart, 655e68 | B4 08 |
| B4 09 + lot:u32 | Increment cart, 655e94; UI 8f27ff | B4 08 |
| B4 0A + lot:u32 | Decrement cart, 65601c; UI 8f2836 checks inbox > 0 | B4 08 |
| B4 0B + pet:u32 + payment:u32 | Checkout, 655f2c; callers 8da290/8da44c | ItemList30, AssetCount, catalog, empty cart |
| B4 0C | Auxiliary option list requested after cart receipt | B4 0D + u16 zero |

Payment 2 is Gold (direct confirmation 8ee2bc reads GoldPrice, availability
8ee5af compares wallet+234). Payment 1 is not enabled in the provisional store.
Auxiliary B40D business semantics remain unrecovered; original empty-list
branch is used. Premium subscriptions use separate C8/3A handling (PREMIUM_ACCOUNT.md).
Rental/auction and other B4 actions are outside this implementation.

Catalog B405: u32 count, then 30-byte records:
`u32 lot, u32 template, u8 enhancement, u16 stock, u32 baseCredits,
u32 baseGold, u32 credits, u32 gold, u8 discount, u16 durability`.
Reader 655bd0/655368; consumer 8eba9c. The consumer overwrites the first
price pair with the second (8ebb55..68). RTTI TSCItem at A79CA4 identifies
lot_id+290, discount+294, count+298, inbox+29C. TItem RTTI A78C54 identifies
Item_id+8, price+38, GoldPrice+3C, EnhanceLevel+4E.

Cart B408: **u32** count, then 24-byte records:
`u32 lot, u32 template, u8 enhancement, u16 stock, u32 credits, u32 gold,
u8 discount, u16 durability, u16 quantity`; tail is
`u32 creditsBefore, u32 creditsAfter, u8 creditsModifier,
u32 goldBefore, u32 goldAfter, u8 goldModifier` (18 bytes).
Original reader 8eb8d0, dispatcher 8ebebc. Catalog receipt clears loading
at 8ebc89 and requests the cart; cart receipt requests B40C.

## Explicit local policy

User authorized provisional assortment and Gold prices in a separate config.
`config/sc_catalog.json` contains 35 offers. `tools/build_sc_catalog.py`
reproduces the initial selection without modifying ordinary-shop configuration
or shared XML. Do not run it over hand-adjusted SC prices unless regeneration
is intended.

Templates, durability and pack sizes come from the existing client-derived
item provenance. Selection is a local mix of source special editions, selected
special goods, and items excluded from the ordinary shop. The source flag
`cant_buy_in_private_store` is NOT evidence of historical SC availability.
There is no recovered original SC assortment or price table.

Local prices: 25 Gold for ammunition/medical consumables, 100 Gold for other
offers. All offers use enhancement 0, no discounts, stock 1000 **per account**.
Stock decrements per purchased pack; catalog can be reloaded from config on
each request. Legacy CFG `packamount` determines the issued ItemRecord count.
Stock/price limits and the total checkout limit of 1000 packs are local policy.

## Persistence and validation

SQLite `BEGIN IMMEDIATE` commits Gold deduction, selected owned pet inventory,
item sequence, sold quantities and cart update together. IDs account for both
all owned bags and private warehouse, including previously allocated IDs.
Inventory/response serialization happens before transaction commit. Rejected
or failed purchases retain the wallet, inventory and cart. Repeating checkout
of an already emptied cart cannot charge again. Direct purchases have no
request identifier; each distinct received direct request is a purchase.

Cart and stock are account-scoped, survive reconnect and use separate tables
`sc_cart` and `sc_sold`. Cross-account recipients, unavailable lots, wrong
currency, insufficient Gold, malformed packets and shopping while in an arena
room are rejected. No items or funds were granted to the main account by tests.

Purchasable templates can include items whose gameplay effects are not yet
implemented (repair/upgrade kits, special explosives, some complex armor).
This restores their purchase/inventory path, not those effects or enhancement
mechanics. Existing supported armor/equipment rules remain in force.

## Verification and user test

- 297 unit tests pass, including 9 SC tests: catalog chain, direct purchase,
  multi-item cart, persistence, account isolation, insufficient Gold, database
  rollback, stock exhaustion, warehouse ID allocation, concurrent checkout.
- Original x86 verifier: 3 catalog cases (empty, distinct sentinel fields,
  all 35 configured offers), 2 cart cases, 6 request writers. Original scalar
  decoding, record accessors and catalog consumer execute; allocation and UI
  helpers are isolated. Full byte consumption and native loading flag checked.
- Evidence: `evidence/sc_shop_native.json`, `evidence/sc_unit_tests.log`,
  `evidence/sc_*.asm`. `python tools/verify_sc_shop_native.py` reproduces it.
- Visual display and mouse-driven purchase still need user confirmation.

Run `python tools/run_reservation.py`, open «Товары SC», select a mercenary,
buy one item for Gold, then check inventory and balance. Also add two items to
the cart, remove one, buy the remainder for Gold, and check persistence after
reopening. Price edits belong in `config/sc_catalog.json`.

## User verification and icon correction

User confirms direct purchases and inventory persistence in the live client. Eight
legacy icon filenames were absent, confirmed by client log NOT FOUND. Replaced
references via tools/normalize_item_icons.py (also integrated in fixture builder):
Smoke Grenade uses itm_stungrenade.png; Molotov uses itm_shampagne.png (bottle substitute); Land Mine uses
itm_mine_green.png; Rags uses military level1 torso/legs; Raider uses battle
level1 head/torso/legs. These are explicit artwork substitutes, not recovered
originals. Evidence sc_icon_replacements.json records asset hashes. Audit confirms
only eight image attributes changed and all referenced image files exist; SC and
ordinary shop configs unchanged. Client restart required to reload shared XML;
new visual appearance remains for user verification.
