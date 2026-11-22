# Player feedback, 2026-11-04

Finish the first batch before the additional reports. The first server patch is deployed (46 isolated hosted checks passed); client release 2026.11.04.1 is published and its HTTPS manifest/blob hashes verified. See `server-deploy.json`, `server-validate.json` and `publish.json` in the report directory.

Real hosted clients verified distinct mine armor colors, the saved mine portrait, immediate crate transfers before inventory OK, and the stock tab without the bonds modal. Initial deposit rendering and character exchange have automated coverage; their final graphical checks remain open. The user clarified that icons stay inside their frame but sit right of center. Compact shop/HUD item origins are corrected by two pixels in release 2026.11.04.2 (HTTPS verified, three native execution tests passed at two load bases). Dog-return graphical verification was interrupted by an existing SQLite lock during a private NPC turn; it is not marked verified.

Follow-up server fixes are deployed (`followup/server-deploy.json`, 66 isolated hosted checks): training clears an old encounter return; failed token payment closes the unpaid room with a Russian message; Hammer Slash requires a primary hammer; range/encounter scenes retain saved portraits. Private NPC turns run in one journal unit with at most three SQLite-contention attempts; injected failure after actual NPC actions proves rollback before retry. RMB Upgrade resolves a valid kit in the same account's bags when the native request omits its ID; an explicit stale ID never falls back. Clan member count now displays current/capacity; the actual native client showed Steam 1/10.

World fixes are deployed (`world/server-deploy.json`, 68 isolated hosted checks): native city-panel acknowledgements no longer trip the survival/ranked search mutation guard; mining standings use net settled payouts after tax and escort/raider division, as confirmed by the user. Sales do not reduce lifetime earnings. Reserved QA logins, explicit exclusions, retired and orphan characters stay out. Two simultaneous production TLS clients received all three pages matching authoritative receipts; the actual graphical client displayed eight extraction rows. Native readers establish the last row word as ranking place, not character level.

Population projection initially passed component checks but the real map tooltip still showed zero: native 79 polling bypassed the projection. The tooltip follow-up is deployed (`tooltips/server-deploy.json`, 36 isolated hosted checks). It covers that path and queued town updates, and prevents private contract markers from entering the shared town cache. Tests exercise real contract parties and preserve territory extensions. The published graphical client now shows Denver (1), matching the one connected QA account after native tooltip polling.

A native Range escape exposed another transition gap: after a valid border escape the server sent only the room-close acknowledgement, leaving the combat scene under city controls. The transport now also sends the completed battle view transition for town returns, as it already did for road returns. A regression first reproduced the missing F0/449 over encrypted sockets; 39 isolated hosted checks then passed and the one-line fix was deployed (`range-exit/server-deploy.json`). Repeat escape preserves saved pets and money. The published graphical client now returns cleanly to Range after border escape; the old combat scene is gone. With no free tokens the native selector disables that option and selects credits; the server rejection path is automated coverage, not a forced GUI demonstration.

The November 5 avatar follow-up is deployed (`avatars/server-deploy.json`, 74 isolated hosted checks). Idle city heartbeats no longer query or resend unchanged portrait assignments. Ordinary passive HP recovery now sends targeted status4 instead of rebuilding a full profile and resetting the portrait. Existing root health-only changes were preserved; only the minimal hosted recovery change was added to the candidate. Two simultaneous production TLS peers received zero unsolicited avatar packets and zero full profiles during four idle seconds; explicit reads retained their distinct saved choices (`avatars/hosted-tls.json`).

The reserve/ready clarification exposed a remaining zero-avatar native66 followed by a delayed FC assignment. The follow-up now projects the saved account-owned avatar directly into every outgoing city profile, including initial login and inventory/result refreshes, without changing canonical pet storage. Roster changes no longer request another heartbeat snapshot. This is deployed (`avatar-cards/server-deploy.json`, 37 isolated hosted checks), with all 175 tables and 67 accounts preserved. In the production graphical client, reserve and ready changes kept the chosen portrait; all 19 observed full profiles retained the correct selection (`avatar-cards/gui-verification.json`). The RMB Upgrade graphical path also succeeded: one kit transferred from warehouse, Beretta upgraded +0 to +1, and exactly one kit consumed.

Client 2026.11.05.1 bounded one native portrait caller, but the real battle HUD uses another caller (9DAAE5); graphical testing caught the oversized selected-card portrait. Release 2026.11.05.2 includes that caller, preserving inventory/gallery draws and image caching. The native execution regression covers both bounded callers and two unchanged callers at both relocation bases. Publication changed only 73 existing Silver bytes, preserved the other 6979 records, required no server restart or database write, and passed HTTPS hash verification (`battle-portraits/publish.json`). The published native client now displays the selected portrait inside the battle frame; passive observation confirms the actual HUD uses a 40 by 40 draw (`battle-portraits/gui-verification.json`). A fresh paid Range practice, border exit, return to Range and subsequent reserve/ready changes kept the saved portrait.

Native map loading also clears actors after the initial FC portrait packet. Portrait assignments now replay after the client's 36 load acknowledgement, including private reconnects and shared battles with global actor IDs. The regression first failed in private loading and shared two-account loading, then passed after the fix. Eighty isolated hosted checks passed and five runtime files were deployed with a fresh database/code/config backup (`avatar-loading/server-deploy.json`); all 175 tables and 67 accounts were preserved. The real Range client displayed its selected portrait immediately after loading. Three older Range assertions fail identically on unchanged production code: disabled gold payment and pre-road-update city coordinates. Their baseline evidence remains in `avatar-loading/known-baseline-checks.json`.

Two simultaneous production TLS peers additionally verified three reserve/ready cycles, all returned profiles carrying the persisted portrait, no deferred FC resets, and zero idle avatar/full-profile packets during four seconds (`avatar-cards/hosted-tls.json`). The initial acceptance harness accidentally sent two pings when polling; its surplus acknowledgements made it inspect old replies. Sending one ping per fence corrected the harness without another server change.

Fog now keeps registered hidden actors off-map without first deleting/recreating the same model. Tests cover repeated ordinary/infected-style dog fog transitions in three battle modes, hidden coordinates/HP privacy, legacy probe removals, and retaining corpses without replaying death. This is deployed but still requires final graphical confirmation; do not claim model rendering is verified from codec tests.

The dog-model report is now specific: the model becomes distorted after disappearing into fog and being discovered again. Do not mark this fixed based only on portrait-field correction or server visibility codec tests.

The final mine acceptance used two adjacent owned soldiers in a real shared hosted mine. Ordinary TLS6E moved one bandage from bags 4/6 to 3/7, then back to 4/6; the normal mine exit also passed (`mine-exchange/hosted-tls.json`). The graphical mine loaded both cards and kept the selected avatar. The user confirmed that the native exchange action is X or the Exchange button beside inventory. That graphical exchange confirmation remains open: another game occupied the foreground during the last attempt. Initial deposit rendering was not observed because the generated deposits were still outside sight. Infected dog visibility observations include repeated hide/reveal cycles; ordinary-dog rendering and the live dog-escape origin remain unverified graphically.

The two disposable QA accounts were removed after normal mine exit and zero owned checkpoints. Cleanup took a fresh SQLite backup, removed only account-owned rows and exclusively QA match metadata, and verified every unrelated row, the schema and foreign-key state in the same transaction (`qa-cleanup-final.json`). A real player's shared mine history and payout were preserved. The older creation-time player fingerprint differs because real play occurred during QA; the transaction-level unrelated-row check passed. Existing player accounts and TestClan were retained.

## First batch

- Weapon picture shifted in the combat character card (confirmed by the user).
- Shared mine character/armor colors do not match participant colors.
- Shop STOCK button opens bonds administration.
- Mine deposit does not always appear on initial load.
- Combat item exchange fails in mines.
- Reservation crate transfers must save immediately, without inventory OK (confirmed by the user).
- Avatar selection does not appear.
- Dog encounter exit leaves a gray screen; return to the global map at the encounter origin.

## Additional batch, queued after the first

- Shrek holding a shield shows Hammer Slash without a hammer.
- Training returns to an old dog encounter position; selecting Range teleports there.
- Training without tokens produces an English error and blocks travel until restart.
- Upgrade Kit in inventory is not accepted by RMB Upgrade.
- Refreshing global presence during matchmaking is rejected as an equipment change.
- Ordinary/infected dog models intermittently distort.
- Mine/city occupancy shows zero while a player is inside.
- All mine uniforms have the same color (additional evidence for the first batch).
- Clan member count displays capacity/current instead of current/capacity.
- Mining ranking does not list mined crystals.

## Safety and evidence

Use the hosted baseline and candidate in `work/player-feedback-20261104`; the main checkout predates current hosted changes. `phase2-baseline` contains fresh verified copies of 13 follow-up targets, read after the first deployment. Do not upload local player data.

Reports are under `reports/player-feedback-20261104`. Disposable QA accounts use the excluded reserved namespace; remove only these fixtures after verification. The user explicitly authorized a short restart with connected players. Preserve active battles/checkpoints and make a fresh backup before any further update.

Graphical dog encounter `94334842-5e29-4720-a495-7ebd90947a50` began at (-81, -243) for this task's first QA account. At 15:23:45 UTC its private NPC movement failed at `BEGIN IMMEDIATE` with `database is locked` and the match was quarantined. The owned graphical helper was closed afterward. This owned failure has since resolved naturally and its checkpoint is gone; do not touch unrelated quarantined fixtures or real players.

Two unused launcher staging executables in `/root` were compressed in place to recover deployment headroom. Verified gzip copies are also retained locally in `.secrets`. Original and compressed SHA-256 values are recorded in `disk-archive.json` and `disk-archive-2.json`; decompression restores the original bytes. Live launcher publications, database and historical backups were not removed.

Two further unused PR39/PR40 launcher staging executables were archived the same way before release .2. Both remote gzip archives and local verified copies remain; exact hashes and available space are recorded in `disk-archive-3.json` and `disk-archive-3-complete.json`.

The old root staging installer `TIO-Launcher-map42-dd3f9e84b294.exe` was archived losslessly to adjacent `.exe.gz`, with a verified local copy in `.secrets`; hashes and space are in `disk-archive-4*.json`. Restore with gzip decompression if that old staging path is needed. Current launcher publications and code/database backups remain intact.

To preserve deployment headroom, two identical immutable copies of launcher 0.1.30 now share an inode after full SHA-256 and permissions checks. Both original paths and bytes remain; see `avatars/disk-dedup.json`. Regenerable completed validation stages alone were removed (`avatars/stage-cleanup.json`).
