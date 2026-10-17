# Battle member numbers (2026-10-04)

The native name-row renderer at `9577AA` reads the member slot's byte
`+11C`, adds one and appends it to the name. This is turn order, not level.
BattleMemberList25 does not supply this field, so all rows showed `1`.

Native BattleMembersArranged71 supplies `u8 count`, then `count` pairs of
`u32 character_id, u8 zero_based_order`. Dispatcher `A0B234` selects callback
`A0ABF8`; setter `A0ABC8` finds the ID and writes `slot+11C`. The callback
sorts member slots by this field.

Shared battles now send71 immediately after25 at initial scene load and
reconnect. Online-status updates also resend the same order. IDs use the
same local-character alias as25. Numbers follow the authoritative room's
interleaved sequence A1, B1, A2, B2, etc. Dead spectators retain their original
number; the existing turn scheduler continues to skip them.

Validation:

- `python tools/verify_members_arranged_native.py`: original dispatcher,
  reader, ID lookup, sorter and numeric renderer, including reversed input
  slots for two, four and eight players. Managed copies isolated.
- `test_shared_team_arena`: initial packets for both accounts, scene reload,
  identity aliases and online updates for team and wall modes.
- Hosting candidate tests run against a copy of the deployed code, without
  copying or modifying hosted player records.
- `tools/verify_hosted_turn_order.py`: fresh QA accounts and public encrypted
  TCP; both views' order packets and the next actual turn owner. This is not
  validation in graphical clients.

Reports and deployment manifest are in `reports/turn-order/`.

Deployed together with post-battle treatment on 2026-10-04. Public hosting
checks passed with two independent accounts in wall mode (eight slots) and
team mode (four slots), including the actual next turn matching number2.
Native dispatch, setter and renderer checks remain distinct from validation
with graphical clients, which the player still needs to perform.
