# Russian and English localization — 2026-10-13

Published launcher: [0.1.8](https://ti-reborn.com/downloads/TIO-Launcher-0.1.8.exe).
Published client resources: `2026.10.13.2`.

## English startup repair — 2026-10-14

The avatar release changed Silver's SHA256 from `64f377d0...` to `d533d7ec...`.
Launcher 0.1.7 pinned only the former image and stopped English startup even
after a successful file check. Launcher 0.1.8 supports both exact reviewed images,
with ten guarded caption patches per image. Unknown DLLs and changed caption
memory remain rejected. The native DLL is never rewritten by caption translation.

Regression checks reproduced the failure on 0.1.7 and passed native English
startup on 0.1.8 using the currently hosted DLL. The actual Play button opened
the English main menu through validated production TLS. Account login and world
or battle actions were outside this startup repair's graphical check.
Publication used fresh remote database/code/config backups and did not restart
services. Evidence: `reports/english-startup-fix-20261014/`.

Launcher 0.1.8: 118937760 bytes, SHA256
`9714367635045e0ec7011b153f13ef3403803fad974ffa61e04f569cdc4a24f2`.
Fresh verified backup: `/root/tio-before-launcher-662v4t5t`.

Close the game, open the launcher, check files, select **Русский** or **English**,
then press Play. The launcher saves the selection and applies it before startup.
Older launchers continue to use the canonical Russian resources.

## Translation coverage

Historical English Total Influence Online references were found online, but no
compatible downloadable current English client was verified. The inspected
hosted client already included an original English language file. Its existing
translations are retained; 995 missing keys are filled. The resulting file
contains 3076 keys and covers all 3073 Russian keys, with matching placeholders.

The pack translates tutorial/quest text, battle-log templates, help and the
in-client agreement. Both Russian and English resource overlays are published.
The launcher interface, news and installation dialog follow the selected language.
Ten fixed captions in the current SHA-pinned `silver.dll` are translated only in
the English process's memory; the native file on disk stays unchanged.

The shared hosted server renders built-in system chat and error messages for each
recipient's selected language. Account names, character/clan names, player chat,
saves and balances are preserved. Existing TIOT v1 flag 0 selects Russian; flag 1
selects English. Other flags are rejected. Both TLS channels retain certificate
validation and the original native protocol.

New text was machine-translated with placeholder checks and some terminology
corrections. Translation services are used only during the optional asset-build
step, never while playing. Full human proofreading and visual acceptance of
every inventory, quest and battle window remain outstanding. Text embedded in
raster artwork is not covered by language-key validation.

## Verification and deployment

- Seven localization checks passed: complete language-key coverage, placeholders,
  resource schemas, recipient selection, opaque player chat/names and typed statuses.
- The isolated hosted-source TLS suite ran 12 cases: 11 passed and one Windows
  directory symlink test was skipped. An unrelated older local multi-account assertion still
  expects the previously removed stale foreign-inventory error packet.
- Final launcher checks passed: 14 language checks; updater integrity/resume/
  rollback cases; TLS isolation/certificates; self-update; installation paths;
  all ten native caption buffers and rejection of unexpected memory.
- Two disposable production TLS protocol clients logged in and entered the shared
  world with different languages. Private bank responses differed by locale;
  Cyrillic player chat was preserved. QA accounts used the reserved ranking-excluded
  namespace and were removed afterward. All 13 existing game accounts remained;
  unrelated rows and SQLite integrity were checked. No QA clans were created.
- Actual graphical QA verified English native startup through the launcher,
  the agreement, main menu and screen settings, including the in-memory captions.
  Russian/English switching, persistence and the English folder dialog were checked.
  This does not constitute complete graphical world/battle acceptance.
- Full trusted HTTPS downloads of the versioned launcher and alias matched the
  reviewed EXE; both self-update manifests, download pages and metadata passed.
  All services remain active; the launcher publication caused no service restart.

The deployed server candidate was built from the actual hosted source rather than
uploading the older local server checkout. Hosted fixes were retained. Remote
database/code/config backups were taken before each update; local player data was
never uploaded. Latest verified backup: `/root/tio-before-launcher-awtx2jwv`.

Evidence is in `reports/english-localization/`: `deployment-apply.json`,
`message-completion-deployment.json`, `hosted-language-verification.json`,
`native-english-probe.json`, `final-*-checks.json`, and
`publication-final/verification.json`. All 11 published language blobs also
matched the local reviewed pack over trusted HTTPS in
`published-resource-verification.json`. Actual GUI observations are recorded in
`graphical-language-verification.json`; these were performed with the
`computer-use` skill and `@oai/sky`.

Historical launcher 0.1.7 EXE: 118921376 bytes, SHA256
`66d3cfb4c5150352f360ff7776384899f5d753e257b37db53415d4a51395efdd`.

## Sources and maintenance

`assets/english-localization/translations.json` stores the offline translations;
`assets/english-localization/runtime/` contains the generated client resources.
`config/english_translations.json` contains server translations with explicit
metadata for translated status fields. `tools/build_english_localization.py`
builds resources from the inspected baseline and rejects missing translations,
Cyrillic residue in English language values, and changed placeholders.
`tools/build_native_english_captions.py` builds the exact native caption plan.

New server-owned messages should use `encode_system_message`; player-authored chat
must continue to use `encode_message`. New client releases that change Silver's
hash require a reviewed caption plan and a launcher release before the client
update is published; do not relax the native signature guards. Rebuild the plans
with `python tools/build_native_english_captions.py --image <reviewed-old.dll>
--image <reviewed-new.dll>` and run `--native-english-self-test` and an English
native startup check for every supported image before publishing.
