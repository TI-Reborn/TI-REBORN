# Item effect tooltips — 24 October 2026

## Confirmed cause and scope

The medkit tooltip builder in the published `silver.dll` always formats
`c026` (healing) from the item's power field. Several nonmedical consumables
use that client presentation class with zero power; their actual effects are
implemented independently by the authoritative server. Consequently a trainer
or maximum-health injection incorrectly displays “Heals 0 hp”. Changing the
client item class or healing power would also change native use routing.

The bounded adapter replaces only the generic healing/AP rows for twelve
known nonmedical effect templates. Name, requirements, weight, ownership and
other common tooltip rows retain the original implementation. Unknown IDs and
ordinary medical items retain the original path. No item XML, server rules,
effects, purchase restrictions or saves change.

The original manual, printed pages 80–82, and the supplied screenshots were
checked against the existing authoritative policy. Presentation values are
generated from `config/battle_item_effects.json` and
`config/combat_completion.json`, rather than maintained as a second rule set.

| Templates | Description |
| --- | --- |
| 35 | Vision Injection: +1 sight cell, 10 AP, 10 turns, 15-turn cooldown |
| 5002 | Night Vision: +2 sight cells in darkness, 3 AP per turn |
| 5003–5005 | Light / Improved / Ultra Trainer: +30 / +50 / +100% XP, one hour |
| 5006–5008 | Advisors: +5 / +10 / +20 rank points, one hour |
| 5009–5011 | Experience blockers: block XP gain for 1 / 2 / 8 hours |
| 5012 | Injection HP: +10% maximum HP, 8 AP, 10 turns, 15-turn cooldown |

Health Injection (20) is a different medical item: it retains native healing
text, including 100 HP. It is deliberately absent from the replacement table.
The existing Night Vision emulator armor policy is outside this text fix.

## Files and compatibility

- `deploy/item_effect_descriptions.py`: pure descriptions and additive CP1251
  localization extension; conflicting keys and unexpected scope are rejected.
- `deploy/client_item_effect_tooltips.py`: exact source SHA guard, one CALL
  replacement, three PE header fields and a 16 KiB PIC section extension.
  No existing relocation is overwritten. The original metadata lookup remains
  the fallback. Unicode temporaries are released through the native RTL.
- `launcher/NativePasswordLimit.cs`: recognizes the exact candidate SHA as
  compatible with existing native hooks. Mutated/unknown images remain refused.
- `tools/publish_item_effect_tooltips.py`: prepares and publishes exactly
  `silver.dll`, `base/russian.lng` and `base/english.lng`. The manifest is
  compared to the actual hosted revision before atomic publication. It backs
  up the hosted database, previous code/config and the three previous assets.
- `tests/test_item_effect_descriptions.py`: six portable regression tests.
- `tools/verify_item_effect_tooltips_native.py`: isolated x86 verification of
  original and candidate paths, including relocation and medical controls.

Client base SHA256:
`7fd0a3b221e6bd967faed999de90b77b54f04ec16864fc4ea85d19b6d68fbe96`.
Candidate SHA256:
`28f33ff6a920182eeb7a81b9d3c30853081f3f52c7d505da15b54de97c01b2ad`.

## Verification

- Original native execution reproduces zero-healing text for every affected
  item; the candidate produces the expected descriptions. Sixty cases cover
  twelve effect items and three medical controls, Russian/English, and two
  image bases. Medical controls preserve 100 / 24 / 15 HP and the original
  metadata lookup. Stack balance and preserved caller registers are checked.
- Six new tests pass and are included in the portable baseline: **591 tests
  passed**. `python -m server --check` passes.
- Launcher compatibility regression was red before adding the exact image
  mapping and green afterwards. Password64, all ten native English caption
  buffers and the existing weather patch pass their targeted self-tests.
- Broad updater and language-overlay self-tests are blocked by the user's
  running game process; their existing “close the game” guard fires. The
  player process was not stopped or changed to run these checks.
- The x86 harness substitutes managed allocation, localization and formatting;
  it is not a graphical-client rendering or multiplayer gameplay acceptance.
- The published launcher started the published DLL in a separate owned QA
  client through its normal certificate-validated TLS route. All twelve
  Russian descriptions also passed execution of the actual adapter with the
  real localization getter and managed Unicode RTL at a relocated image base.
  This diagnostic used private rows and a temporary continuation return in
  that owned process; it did not render in-game tooltips or authenticate a
  player. No hosted QA accounts were created, and the owned client was closed.

## Release and rollback

Published launcher **0.1.34**, then client **2026.10.24.1**, on 24 October.
Existing launcher
publication tools preserve versioned downloads and create a fresh verified
SQLite/PostgreSQL/code/config backup. No game service restart is required.
Both publication receipts confirm zero service restarts. The three client
blobs and manifest were independently verified through trusted public HTTPS.
The user's running game was left untouched.
Public launcher aliases, versioned download, both self-update origins and
download pages also pass HTTPS verification. Service PIDs/configuration and
32 game accounts remain unchanged; hosted SQLite integrity is OK.

The publication receipts remain outside Git. Before rollback, compare the
live manifest against the exact released bytes and restore only its previous
manifest from the private backup. Previous immutable blobs are retained.
Do not restore the backed-up player database for this presentation rollback.
Players must close the game and reopen the launcher to load the new DLL and
language resources; already running clients keep their old presentation.
