# Phase 6 integration contract

Released backend files: `tio/market_inventory.py`, `tio/private_shops.py`,
`tio/sc_auction.py`, both new `tio/protocol` modules, `server/private_market.py`,
`config/private_shops.json`, `config/sc_auction.json`.

At server startup instantiate one `PrivateShopStore(database)` and one
`SCAuctionStore(database)` against the hosted database. Their new tables are
additive. Constructors never seed accounts, wallets or goods into player saves.
System auction catalogue is explicit server policy; lot generation is persistent
and uniqueness constrained. Original numeric SC tariffs are unknown.

After authenticated native character selection create
`PrivateMarketSession(shops, auction, session.account,
character_id=session.probe_character_id)`. `account` is the selected save owner,
never the public name or a client owner field. The backend compares canonical
human identities to reject trading among one login's character slots.

Route `AE` city packets to `market.handle(packet, allow_mutation=city_idle)`.
Return its native packet tuple after the enclosing gameplay transaction commits.
Listing/query operations are read-only apart from additive shop identity. Fence
mutations during shared battles, results/recovery checkpoints, mine sessions and
any other ownership lease. Refresh the selected session's complete saved pet
inventories after mutation: sales can escrow loose items directly from owned
inventories. Acquired/refunded items arrive on the private warehouse. Offline
counterpart balances and warehouse are durable; their sessions must refresh
their own snapshots on the normal city poll. No stale cached inventory may
overwrite these writes. `transaction(database)` is supported by every new
backend action; no nested scope commits the outer gameplay action.

`market.refresh()` every normal city poll is internally limited to 2 seconds;
it produces own assets, warehouse and queried public traders. It also performs
the SC timer tick. Call `auction.tick()` from a shared server timer at least
every 0.5 seconds even when nobody has the market open, so offline autobots act
in the last second. Each tick is atomic/idempotent: once a bot is chosen the lot
deadline advances. Server downtime misses the window and closes a lot without
retroactive bids. Unused bot budgets refund on deletion and closing. Overflow
refunds/proceeds remain durable `market_payables`, collected when own balances
are next refreshed.

Native private market `AE`: 01 query(kind u8, template u32), 03 select(trader
u32), 06 buy(trader, count, item-position/units), 07 fill purchase request
(trader,count,request-position/owned-instance/units), 08 publish sales
(package u8,count,owned-instance/units/f32 unit credits), 09 publish requests
(count,template/units/f32 price/enhancement u8/has-filter u8), 0A signature
(UTF16 CString). Replies 02 traders, 04 sales, 05 purchase requests have original
reader proofs. Public stable trader IDs are `0x40000000+shop.id`; the own native
character ID maps only to the owned shop. A trade consumes its quote; reopen
03 before another trade. This rejects retransmitting a completed partial buy
without silently treating it as another purchase. Trader conditional u32 field
semantics remain open; current projection emits 1 with no extension.

Until SC S2C is recovered, route native `BD` to `market.handle_sc`, and ordinary
chat starting `!sc` to `market.command(text, allow_mutation=city_idle)`. Both
return display lines for a valid native server-chat packet; send own balances
after monetary actions. The fallback offers current/closed/cabinet/history,
paid bids, prepaid bot From/To/count, deletion/refund and winner purchase/mail.
It is not a completed native SC window. The original winner purchase is a
separate confirmation: BD07 requests the winning lot; BD09 flag1 buys, flag0
defers. BD14 mode1 installs three u32 bot fields; mode0 deletes/refunds.

Validation: `python -m unittest discover -s tests -p test_private_market.py -q`
19 tests pass; `python tools/verify_private_market_native.py` executes 14 original
C2S builders and 2 nonempty private-goods numeric readers. Evidence:
`evidence/private_market_native.json`. These are local disposable saves and x86
ABI checks. No hosted deployment, remote provisioning or graphical acceptance
was performed by this agent.
