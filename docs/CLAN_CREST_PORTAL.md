# Clan crest portal and original client transport

Phase7 source package only; no hosted mutation or publication performed by this
package. Production frontend build and hosted acceptance belong to the parent
integration task. The completed phase6 archive is unchanged.

## Portal and private gateway

`/ru/clan` and `/en/clan` select clan or alliance and use the actual ACTIVE portal session and its verified
`gameUsername`. The account page links to the crest page after the bank link.
Browser input is an owned character slot, a durable request ID and raw BMP;
foreign username/account/owner query parameters are rejected.

- `GET /api/clan/status?slot=1..5`: session-bound authoritative character list,
  current clan/name/crest ID, personal credit balance, CREST authority and cost.
- `POST /api/clan/crest?slot=1..5&kind=clan|alliance&requestId=<16..128 ASCII ID>`: existing Origin
  and CSRF check; `Content-Type: image/bmp`; streamed maximum824 bytes. The
  canonical uncompressed24-bit16×16 file is822 bytes, with bottom-up height+16.
  Compressed/paletted/wrong-size/reserved/trailing data is rejected. Original
  ti.exe skips image loading for top-down height−16; this is a verified client
  compatibility restriction, now also enforced by the shared backend validator.
- Alliance `remove=1` requires an exact empty body and a fresh/replayed operation
  identity; clan removal and a supplied replacement body with remove are rejected.
- `GET /api/clan/crests/<uint32 positive ID>`: public, canonical validated BMP,
  SHA256 ETag, nosniff, immutable one-year cache. Error replies are no-store.

All portal game-data IO uses the existing private `BANK_SERVICE_KEY` and
loopback `BANK_GATEWAY_URL`; no key is exposed to a browser. New private routes
are `/v1/clan/status` (JSON POST username+slot), `/v1/clan/crest` (raw BMP POST,
trusted X-Game-Username/X-Character-Slot/X-Request-ID and X-Crest-Kind headers;
alliance removal uses X-Crest-Remove:1 with empty body), and
`/v1/clan/crests/<id>` (GET). Existing bank/payment routes are unchanged.

The authoritative write resolves the linked account and owned slot inside one
SQLite transaction, then calls `clan_benefits.set_crest`. That helper checks the
current leader/CREST authority, debits1000 personal credits, creates a validated
BMP+digest, updates the clan crest and stores a durable receipt. An identical
request replays its receipt; an already-current identical picture under a new
request costs0. Conflicting replay, lost rights or insufficient funds fail.
Storage faults roll back picture, receipt, ledger and debit together. Status and
public image reads use SQLite mode=ro with no schema writes.

Alliance writes call `AlliancesStore.set_crest(account,bmp|None,requestID)` inside
that same SQL transaction. Only the current head of the current leading clan of
an active alliance may act, including replay/removal. Delegated clan CREST rights
do not grant this authority. Original russian.lng m471 confirms1000 credits for
installation and empty-path removal. The1000 **personal** credits payer,
unchanged-image0 and removal0 are explicit accepted emulator policy. Aliased
slots resolve their own saved character wallet. No treasury or Gold is debited.

The shared `clan_crest_blobs.id` is the only image sequence. Clan blob owners are
positive clan IDs; alliance blob owners are negative alliance IDs. The separate
`alliance_crests` pointer is checked against that typed owner before use. A clan
and alliance with the same numeric storage ID and same picture receive distinct
global image IDs; content cannot be confused through a wrong typed pointer.
Removed/replaced blobs remain immutable and fetchable by exact global image ID.
`snapshot` and `alliance_for_clan` headers now include read-only `crest_id`.

Root integration should retain the existing authoritative wallet refresh so an
online character sees the portal debit. Crest ID is already projected by
`server/public_profile.py`; root owns native54/clan service projection and59/5A
routing. This package does not change shared gameplay routes or wallet code.

## Original Silver and ti.exe proof

`tools/verify_clan_crest_native.py` executes the installed read-only original
files, pinned Silver SHAa73396748ea5c3530157db53592a9f3e04744592c3711f38d40d4877b785de11
and ti.exe SHAe288de090e162660604750075c3e633f60744ee8a24915a9bc24e8cc39ee3f1c.
Evidence: `evidence/clan_crest_native.json`.

Silver54 reader6e69f8 stores the u32 immediately following the clan level in
character+0x48c. Its call68a094 registers/follows
SILVER_RegisterClanCrestBuffer_AddFunction (export4f2414), with stdcall arguments
crestID:u32, kind:u8(0clan/1alliance). Original ti.exe wrapper71c314 invokes
719a00, which queues uncached positive IDs. Tick719d94 asks for missing images;
there is **no crest HTTP URL** in this path.

| Kind | C2S request | S2C response |
|---|---|---|
| Clan | `59 id:u32` | `5A id:u32 bmp_length:u16 bmp:bytes` |
| Alliance | `AF06 id:u32` | `AF07 id:u32 bmp_length:u16 bmp:bytes` |

Original ti.exe request builders719504/719590 execute their numeric writers.
Dispatcher719904 accepts5A/AF07; reader719628 consumes ID, length and bytes into
a1024-byte native buffer, then hands exact bytes to the stream/image loader.
Server must enforce its canonical max824 bytes before replying. Cache path is
`<game data root>..\icons\ic<ID>.bmp`. Original queue/cache lookup deduplicates
**only by ID**, so a future alliance implementation must allocate IDs from the
same global crest blob sequence as clans.

The probe verifies exact822-byte payload delivery, consumed829/830-byte packets,
zero-ID exclusion, duplicate exclusion, requested/completed queue flags, and
repeat-tick suppression. Delphi allocation/strings, filesystem, stream object,
renderer and network send are explicit stubs. It does not certify pixels in a
live graphical client or a hosted exchange.

Alliance rights and policy provenance are detailed in
`docs/ALLIANCE_CREST_RESEARCH.md`. Root owns actual54/AF0D/AF0F/profile projection,
59/AF06 routing and canonical5A/AF07 content delivery; no native upload opcode is
introduced by this package. GUI rendering and hosted exchanges remain separate
acceptance work.
