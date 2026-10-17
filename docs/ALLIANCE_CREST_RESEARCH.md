# Alliance crest: evidence and implemented server policy

Read-only evidence review and bounded local backend implementation on2026-10-08.
No hosted mutation or request performed; disposable tests use ordinary accounts.

- Original manual printed20 (`reports/chat-presence/manual.txt`, PAGE21,
  lines878–881): the head of the leading clan is the alliance head, including
  automatic replacement when that clan changes its head. This alliance head may
  set the alliance icon. Ordinary members with delegated clan CREST permission
  and heads of other allied clans are not given this right by the manual.
- Installed original `base/russian.lng` SHA
  cd711d83be980858c8b205a3114e61c38a349f0a899c80a26ce5f0c8547e1403,
  entrym471: installation costs1000 credits, picture no larger than16×16;
  an empty file path removes the current alliance icon. Entry s216 is the
  successful removal notification. The file exactly matches the repository
  archive20231004 copy. Silver native6dc13f loads m471 through6675e0 in the
  original alliance crest form.
- The manual and this original copy do **not** state whether that1000 is debited
  from the head's personal wallet or the leading clan's treasury, nor whether
  removal is charged. The native form examined delegates actual accounting to
  the historical server. A payer/removal rule must be explicit emulator policy,
  not claimed as recovered history. Accepted implemented policy:1000 personal
  credits for a changed nonempty crest; identical current content and removal0.
- `tio/alliances.py`: `AlliancesStore._owned` resolves current clan head,
  leading clan and alliance state from authoritative SQL. `set_crest` now checks
  this authority before every write/replay, performs the personal debit and
  typed pointer change atomically with an immutable receipt and alliance audit.
  `snapshot` and `alliance_for_clan` return read-only `crest_id`. Parent integration
  owns `server/alliance_service.py` and `server/public_profile.py` projections.
- `tio/protocol/alliances.py` already has crest fields in AF0D/AF0F.
  `evidence/clan_crest_native.json` verifies original AF06 request/AF07 reply;
  the new `tio/protocol/clan_crests.py` supports these exact packets.

The original ti.exe cache is `..\icons\ic<ID>.bmp` and deduplicates only by
numeric ID across both kinds. Any alliance crest must use the existing global
`clan_crest_blobs.id` sequence. The new alliance pointer table references these
immutable content IDs. Blob ownership is explicitly typed: positive clan IDs,
negative alliance IDs in the existing blob-owner column. A wrong typed pointer
fails closed; no second image sequence is started. Same alliance/clan numeric ID
and identical content receive distinct global image IDs, with no cache collision.

The gateway extension keeps the verified linked username→owned slot mapping;
inside the same SQL transaction, require current head of the current leading
clan and an active alliance, validate canonical BMP, debit the chosen explicit
personal payer once, set/remove pointer, audit and store durable receipt. No request
may name a target alliance, arbitrary game account, clan or payer.

Original x86 evidence also confirms ti.exe does not call the stream/image loader
for a top-down BMP(height−16), although it consumes and acknowledges the packet.
All canonical accepted BMPs therefore use positive height16. This compatibility
policy is documented independently of manual format requirements.
