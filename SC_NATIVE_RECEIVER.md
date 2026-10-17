# SC native receive limitation

`tools/verify_sc_receiver_native.py` executes the original
`SILVER_NET3_PacketHandler` export (`0x9f5548`) from the pinned installed
`silver.dll`, SHA256
`a73396748ea5c3530157db53592a9f3e04744592c3711f38d40d4877b785de11`.

For all 256 BD subcodes the export returns **unhandled** after running all
31 legacy gates, all 13 interface handlers registered by the original startup,
and the original typed classifier (`0x65d034`). The classifier consumes only
the opcode byte. The SC lot and history arrays remain empty. No packet reader
is stubbed; only clock, reference counting and enumerator allocation are
isolated. The registration-call inventory is exhaustive over the mapped DLL
and pinned by the probe. Array address references are confined to the dormant
`game_Auction` unit.

Evidence: `evidence/sc_receiver_native.json`. Reproduce with
`python tools/verify_sc_receiver_native.py`.

This client still has the BD request builders and historical SC UI labels, but
its exported receiver cannot consume a BD lot/history reply. A server-side
encoder cannot restore that path. Original SC window completion requires either
a historical client with a working receiver or a separately reviewed client
extension. `!sc` remains a usable game-chat fallback; it is not native SC UI
completion. No hosted change or graphical acceptance is claimed by this probe.
