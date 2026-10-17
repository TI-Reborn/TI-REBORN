# Shared gameplay bank command adapter

`server.bank_gameplay.BankGameSession(database, authenticated_selected_save_owner)`
uses the existing `tio.bank_economy` SQL helpers. Constructor creates additive
schema and validates an existing character/wallet; it never creates an account,
seeds Gold, resets a save or performs payment-provider IO. Its `BankStore` is
explicitly disabled for checkout. The independently configured web gateway owns
real payment orders and signed confirmations.

Root integration:

1. Recognize `is_command(text)` before packet21 logging or public/party/whisper
   broadcast. `redact_command(text)` returns only `!bank [private]`. Never log raw
   PIN-bearing commands. Consume every recognized malformed command too.
2. Under the shared authoritative gameplay/lease lock, supply current `city_idle`
   and a set of busy **save owners** from real hub sessions and durable DB leases.
   Call `session.command(text, city_idle=..., busy=...)` or
   `session.handle(packet21, ...)`. An existing gameplay transaction is joined,
   with a nested store savepoint for the bank action. An ordinary rejection
   rolls back partial helper writes while preserving the enclosing journal.
   Root must not roll back an ordinary rejected PIN result: its failure budget
   and lock are security state and must commit.
3. A recognized request returns frozen `BankReply(packets, changed_accounts)`;
   unrelated text returns None. Enqueue packets only for the requesting player.
   Public text never contains PIN, request ID or private save-owner/login keys.
   Replies use private server channel22/4; assets use native C839 with securities.
4. `changed_accounts` contains trusted save owners for root refresh only. Resolve
   currently authenticated sessions for those owners; refresh physical inventory
   only while each recipient is idle. Duplicate durable operations return current
   own snapshots but an empty change list. Refresh peers through their own
   `snapshot(items=True)`; do not publicly broadcast this metadata.
5. Item packets are canonical saved PetInfo66/ItemList30/WarehouseList6A. Root
   applies `bank_economy.project_marks` once at final outbound. Never persist
   projected optional owner names or remaining times. Root's ordinary clock runs
   `expire_marks(db, busy=busy)` and refreshes its trusted returned owners, deferred
   while either owner/holder is busy.

Commands (case sensitive; public names require their exact saved spelling):

```text
!bank help
!bank quotes
!bank history [stocks|bonds]
!bank convert GOLD REQUESTID
!bank stocks buy|sell COUNT QUOTE REQUESTID
!bank bonds buy|sell COUNT QUOTE REQUESTID
!bank marks
!bank mark INSTANCE DAYS PIN REQUESTID
!bank lend MARK PUBLICNAME REQUESTID
!bank reclaim MARK PIN REQUESTID [remove]
```

IDs require16–64 ASCII letters/digits/underscore/hyphen. A retry must repeat the
same ID and parameters; a new action uses a new ID. Count/instance/mark/quote are
positive bounded unsigned integers; days use configured maximum365. PIN uses the
existing configured4–12 digits, hashed only by the shared helper. Packet21 text is
limited to200 UTF16 code units. History shows the last12 real quote observations
per requested kind; no inferred missing candles are generated. Exact public
character names resolve through `characters.name` to durable selected save owners,
including secondary slots. Arbitrary login/owner keys are not lending targets.

Read commands work without overwriting live combat inventory; they send no
physical snapshots. Every mutation, including a durable replay, requires idle
city state and an unbusy requesting owner. Lending/reclaiming additionally check
the current recipient/holder. Helper receipts, wallet/item writes and delivery
remain in one SQLite gameplay transaction. Wrong PIN produces a normal private
response and commits rate limits. Unexpected storage exceptions propagate for
root rollback/retry; root must retain command redaction in its error logging.

This makes the shared economy usable through actual city chat once root connects
the adapter. It does not claim an original bank-action ABI, rendered native bank
window, real payment acceptance or hosting deployment. Quotes, calendar, PIN
bounds and mark limits retain the explicit policies in `config/bank_economy.json`.

Automated verification:12 `test_bank_gameplay.py` and19 `test_bank_economy.py`
checks passed. Adapter tests use four normally created character saves, lawful
shop purchases and an isolated signed-payment-provider fixture for Gold; no
administrative wallet grants, real payments or remote provisioning are performed.
They preserve the fourth player's wallet/character/roster/warehouse rows and
verify private replies, canonical inventories, secondary-character resolution,
restart/replay, concurrency, city/busy fences, storage-failure rollback and
ordinary-rejection savepoints inside the outer gameplay journal. The successful
and failed PIN paths prove that committed rate limits survive adapter restart.
