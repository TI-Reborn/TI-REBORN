# RPG launch action icon

Client resource release2026.10.19.6 replaces the rifle graphic in battle action
frame4 with a standalone RPG rocket, matching the olive/brass HUD style and the
rocket shown on printed page39 of the original game manual. The new transparent
glyph was generated with the built-in image_gen tool; the prompt and references
are recorded in `assets/rpg-action-icon-v1/prompt.json`. The full generated
master and the184px registered glyph are retained in that asset directory.

Only `base/ui-hd/battle-controls/hd4-bui-glyphs.png` changes. The1104x1104 RGBA
atlas keeps its six-column grid and184px source cells for46px logical buttons.
All35 other cells are pixel-identical, and the new rocket is centered with
transparent padding. No gameplay parameters, AP, ammunition, input callbacks,
DLL, launcher or server source changes are part of this release.

`tools/verify_rpg_action_icon_native_20261019.py` executes the original enum
lookup and HUD routing on14 attack types. The freshly fetched hosted Silver
has byte-identical verified spans. Only Rocket enum3 selects frame4 and action
-13; Bullet and other attack types retain their original frames. The current
RPG316 item metadata explicitly declares attackType/weaponAttack Rocket.
Native string lifetime and the metadata accessor are isolated; this proof does
not claim a graphical-client battle.

Evidence: `reports/rpg-action-icon-20261019/asset-proof.json`,
`native-icon-routing.json`, `icon-review.png`, and `deployment/`. The review
shows both the enlarged actual button plate and its46px rendering. The scoped
publisher reuses the existing resource release process with a fresh online
SQLite backup, previous code/config/manifest and prior atlas blob. It verifies
the actual hosted baseline before a guarded atomic manifest replacement. All
6605 other client records are preserved. No service restart or player-data
upload/restore is needed. Reopen the launcher and game to download the new atlas.

Published and verified through trusted HTTPS: release2026.10.19.6, atlas SHA256
`628be67bc34847381fd497b6f1bbc8f86f8f6588178c2e72ff9768e6d5c8d34c`.
Fresh backup: `/root/tio-before-rpg-action-icon-_tjpz6ai`. Hosting verification
confirms SQLite integrity,22 accounts and unchanged credentials, native client
blobs, configuration and service identity. Launcher remains0.1.15; this is a
resource update downloaded by the existing launcher.
