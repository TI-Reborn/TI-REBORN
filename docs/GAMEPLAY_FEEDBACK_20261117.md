# Gameplay feedback, 2026-11-17

## Rules

- Fixed crystal sale price: 50 credits. Historical sales and quote samples retain their original prices.
- P90: 4 AP, in the authoritative catalog, catalog importer and published client items.cfg.
- Enter invokes the original quantity-dialog OK handler only in visible battle mercenary exchange. Other dialogs retain their keyboard handling.
- Marked single items may enter the clan warehouse. The original owner, expiry and recall remain intact across deposit and withdrawal. Rental/temporary items remain restricted. Shared custody uses a reserved non-login holder in the existing mark ledger; no schema migration.
- Mine menu exit requires a drill in a living squad member's inventory, including an empty drill, and no living opposing player squad. A raider admission closes both sides' exits for five complete round advances. Reconnect does not reset the deadline. After it expires, physical extraction is available even with a living opponent; menu extraction remains blocked.
- Extraction victory requires 100 crystals in mines 4–6 and 7–10, and 200 in mines 11–15 and 16–20. Below the threshold the result is defeat. Existing crystal distribution remains based on the extracted amount. An empty drill yields no crystals. A positive extraction ends the shared mission as before.
- All shop stock categories are unlimited. Old depleted stock rows are ignored and retained; per-request quantity, money and inventory bounds remain enforced.
- Monster armor in mine 4–6: 160 → 128. Other bands remain 270, 270, 310.

## Verification

- `python -m server --check`: passed.
- `python tools/run_server_checks.py`: 724 tests passed after updating the obsolete finite LE-kit expectation.
- Focused local mine, crystal and mark regressions passed, including real high-level mine 199/200 boundaries.
- Hosted isolated candidate: 104 tests passed on the server's Python runtime and temporary databases; 17 additional credit/shop tests also passed.
- Native Enter patch executed under x86 emulation at two image bases across eight cases each. This does not constitute graphical client acceptance.
- Launcher adapter regions: recon, throwables, flame, rain, contracts all match.
- `python tools/check_handoff.py` could not run: this file is absent from the workspace.
- Legacy full clan/shop suites also contain unrelated pre-existing failures; the same failures were reproduced against the downloaded unchanged hosted sources. They are not represented as passing.

## Release preparation

Authoritative file diff and reports: `reports/gameplay-20261117/`.
Exact hosted sources and candidate artifacts: `work/gameplay-20261117/`.
Server deployment uses `tools/deploy_gameplay_feedback_20261117.py`, with existing baseline hashes, idle/retained-gameplay guards, SQLite backup, code/config backup and data-preservation checks.
Client publication uses `tools/publish_gameplay_feedback_20261117.py`: immutable blobs and atomic manifest transition, exact source identity, changed-byte allowlist and launcher compatibility gate. Client version: 2026.11.17.1.

Closed system journals were losslessly compressed under `/root/system-journals-archive-20261117`; each archive was decompressed and SHA-256 checked before removing the archived original. Recent journals, game data and existing backups were retained. This provided the documented deployment headroom.

Deployment completed after explicit authorization to disconnect idle player sessions. The guard found no retained battles or settlement jobs. All 175 database tables were unchanged across code replacement, all 93 accounts were preserved, and `tio-server` restarted successfully with SQLite integrity `ok`.

Server backup: `/root/tio-before-game-operations-gameplay-feedback-20261117-20261117`.
Client publication backup: `/root/tio-before-ui-modernization-x9qfqyqk`.
Client version 2026.11.17.1 and both changed immutable blobs were verified through trusted HTTPS. All other 7,212 client records were preserved.

The first public TLS QA attempt used an obsolete bootstrap and was rejected before login. Its two excluded fixtures were removed with unrelated rows preserved. The QA harness now uses the current manifest and launcher proof.
Public TLS acceptance passed with two fresh excluded accounts: both received the 50-credit quote, each sold 1,000 crystals for exactly 50,000 credits, both bought LE kits, and the marked P90 was deposited into shared clan storage, shown with its original owner's name to the second account, and recalled by its owner. All disposable accounts, clan and owned item/receipt rows were removed; schema, unrelated rows and existing player data were preserved. Final service health and all 10 installed file hashes passed; 93 accounts remain.

During harness debugging, explicit invitation/success notifications and eventual shared snapshots replaced assumptions about the first queued response. The canonical storage warehouse decoder intentionally rejects outward owner-name branches; the existing mark metadata verifier checks those branches instead. Historical helper imports now bind the current packages before loading fixtures. No additional production changes were needed.

A subsequent independent client publication advanced the live manifest to 2026.11.17.2 during verification. Final SSH and HTTPS checks confirmed that both gameplay files retain the exact reviewed hashes; that newer manifest was preserved.

Graphical clients have not yet been used for acceptance. Enter was checked through native x86 execution, while mine rules were checked through automated multiplayer protocol/integration scenarios on temporary databases.
