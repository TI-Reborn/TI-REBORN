# Treatment after battle (2026-10-04)

Two defects prevented the native result checkbox from working in shared battles:

- Settings C8/37 advertised a zero treatment tariff, although paid treatment
  already charged the configured `credits_per_hp` from `config/recovery.json`.
- Finish callback719F60 runs7196FC (exit2A01), then, when checked, sender8C3D84
  (treatment7C). The treatment contains shared battlefield actor IDs. After
  exit, the server had discarded their mapping to account-local saved pet IDs.
  Treatment before exit was also silently consumed by the results state.

Settings now advertise the configured positive tariff (currently2credits/HP).
The server handles treatment both before and immediately after result exit.
Only the requesting account's mapping is retained on its session, and a new
shared battle clears it. Treatment remains blocked during a new private battle
or search. Existing atomic treatment restores effective maximum health,
including dead fighters, and charges only missing HP. Retry for healthy fighters
costs zero. The unchecked Finish path keeps wounds and money unchanged.
Results retained for reconnect receive the current balance and treated HP.

Validation is recorded in `reports/post-battle-treatment/`:

- Native Finish callback: exact2A01 then7C order, checkbox on/off, ownership,
  wounded/dead/healthy actor selection. GUI/settings/transport glue isolated.
- Native settings reader and price arithmetic: tariff2 and missing-HP totals.
- Eight dedicated unit/TCP checks, including two accounts and exit+treatment
  frames in one socket write, account isolation, retries, insufficient balance,
  malformed/foreign requests, and new-search blocking.
-100 tests passed in a separate copy of the deployed hosting code, including
  recovery, multiplayer, heartbeat, crash restoration and pending turn order.
- Public hosting QA script uses only fresh test accounts. Its live battle ends
  through ordinary attacks, then sends the native Finish request sequence.
  This is an automated protocol check, not graphical-client validation.

Deployment bundles the already-reviewed pending turn-order71 fix. Existing
hosted accounts are never replaced with local data. Installation requires an
idle server and backs up remote code, configuration and database first.

Installed on the hosting service on 2026-10-04. Backup:
`/root/tio-before-post-battle-treatment-_731tqsu`. All57 existing tables had
unchanged rows immediately after installation; the service is active.
The user confirmed the battle ended and both graphical clients were closed.
Two inspected sockets still acknowledged heartbeats but had sent no gameplay
requests for over40 minutes; no checkpoints or settlement jobs remained.
The deployment guard permitted only these exact two long-idle sockets.

Public TCP treatment verification passed (`hosted.json`): ordinary attacks
killed the fresh QA account's fighter, Finish restored0/85 to85/85 and charged
170credits at2credits/HP; a retry charged0. The other fresh account retained
its health and wallet. Real graphical client confirmation is still separate.
