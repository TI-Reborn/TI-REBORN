# Reservation texture replacement

The replacement uses the published 2026.10.06.2 client assets as its source. It covers the 81 fragments in the Reservation procedural profile (village and Military layouts), 270 model resources, and 109 texture resources. 107 material atlases are edited with built-in image_gen; two pure shadow resources are retained verbatim.

Art direction: desaturated post-apocalyptic settlement, weathered boards, chipped concrete and masonry, scratched steel, restrained rust, faded paint, dirt and readable surface details. Each original atlas is supplied as an edit reference. The prompts require its camera directions, component arrangement and silhouettes to stay in place.

## Sources and build

- `assets/reservation-textures-v2/tasks.json`: complete prompts, source paths, dimensions, transparency and shadow classifications.
- `assets/reservation-textures-v2/inputs/`: decoded original references.
- `assets/reservation-textures-v2/generated/`: selected high-resolution image_gen outputs, copied out of the generation cache.
- `assets/reservation-textures-v2/generated.json`: per-texture provenance and generation mode.
- `tools/reservation_texture_assets.py`: published-source inventory and isolated resource bindings.
- `tools/reservation_texture_export.py`: original-size UV registration, original alpha masks, native codec export. Color JPEGs use quality 96 without chroma subsampling. Original masks, black shadows/openings and unused white atlas padding are preserved.
- `tools/reservation_texture_review.py`: original/export comparison sheets.

Client exports retain original dimensions for compatibility with the existing models. High-resolution generated masters are retained for later engine work; this release does not claim to increase the legacy renderer's texture resolution.

## Runtime scope

Cloned `.t` and `.s` resources use unique equal-length names. The only geometry-file changes are referenced resource names; geometry, UV coordinates and door records retain their original bytes. `ground.xml` adds brush groups 10 and 11 and preserves all previous groups, including forest encounters 7–9. Shared source textures remain available to other cities.

`config/reservation_visuals.json` maps the original layout names to the visual clones. `tio/map_generation.py` applies these bindings after the original Reservation layout and collision validation. Layout metadata, map dimensions, collision, spawns, containers and rewards retain their existing rules. Other city profiles and the fixed legacy training map do not use this binding.

## Validation and release evidence

- `reports/reservation-textures/automated-tests.json`: 892 unit tests passed, including visual binding invariants across Reservation modes, variants and seeds.
- `reports/reservation-textures/native.json`: original x86 client brush selector accepts both layers for brush groups 10 and 11 with render stubs.
- `reports/reservation-textures/native-models.json`: original model readers retain house, hangar and gate door records.
- `reports/reservation-textures/asset-verification.json`: allowed geometry substitutions, decoded masks, original dimensions and isolated resource names. Its mask check missed two native BMP32 alpha planes because source and export checks shared a decoder that discarded those planes; see the 2026.10.06.4 correction below.
- `reports/reservation-textures/review-*.png`: decoded original/export comparison sheets.
- Deployment, HTTPS and public-protocol multiplayer evidence is recorded in this report directory when those steps finish. Those checks do not constitute a graphical game-client inspection.

The guarded deployment overlays only `tio/map_generation.py` and `config/reservation_visuals.json`, plus the client launcher release. It backs up the remote database, previous code/configuration and client manifest, rejects active players/unfinished battles, checks the actual hosted baseline, and verifies all previous hosted table rows survive unchanged. It never uploads local player data.

## Published result, 2026-10-06

Client **2026.10.06.3** is published on the existing HTTPS update endpoint. All 461 changed/new client files were downloaded from that public endpoint and checked by SHA256 and size; all other previous manifest records are unchanged. The launcher executable is unchanged. Close the game and reopen TIO Launcher to install the resource update before playing.

The actual hosted source overlay passed 15 isolated tests: 3 visual binding tests, 4 map generation tests and 8 city tests. An initial candidate run lacked the cities test helper; the helper was added to the test-only archive and the complete candidate run passed before installation. The failed candidate did not change the live service or database.

The previous remote database, code/configuration, service configuration and client manifest are backed up in `/root/tio-before-reservation-textures-70knn6xp`. Deployment verified all previous records in 61 hosted tables unchanged and left the service active. Evidence: `deployment.json`, `deployment.log`, `hosted-candidate.json`, `hosted-candidate.log`, `https-release.json` in the report directory.

Public encrypted TCP verification used two new independent accounts (`qrf14561c3a`, `qrf14561c3b`). Both received byte-identical 57×57 maps with the new resource bindings and brush 10, accepted movement, rejected invalid movement with prediction correction, completed repeated turn cycles and received shared observer events. These QA accounts are retained for audit; existing accounts were not used. Evidence: `hosted-1-qrf14561c3.json`.

Post-QA hosted state: service active, database integrity `ok`, 162 accounts (160 existing plus two QA accounts), zero battle checkpoints, zero pending settlement jobs, zero established game connections. See `hosted-health-after-qa.json`. Exported textures were visually reviewed in nine comparison sheets, but no graphical game client was inspected during this update; final in-game appearance still needs that validation.

## Transparency correction, client 2026.10.06.4

User game screenshots showed black rectangles around individual crates. The source `steel_box_01b.png` is actually an uncompressed 32-bit BMP with a native alpha plane. Pillow decoded it as RGB, discarding the fourth byte; the previous export consequently produced an opaque PNG. `ground_ny_detail_32.png` had the same defect. These are the two BMP32 resources in the Reservation texture inventory.

`tools/build_visual_asset_catalog.py` now decodes that plane explicitly. `tools/reservation_texture_export.py` preserves the original BMP32 header, row order and every alpha byte while replacing only the BGR color bytes. Three focused regression tests cover native BMP32 alpha and row order, RGB24 BMP, and RGBA PNG. The earlier shared-decoder mask check did not prove BMP32 transparency; its historical report is retained rather than rewritten.

The hotfix changes only `base/setting/reservation_v2/rveel_box_01b.png` and `base/setting/reservation_v2/rvound_ny_detail_32.png`. Every generated RGB pixel remains identical to 2026.10.06.3; alpha bytes match the original native resources exactly. Dimensions, models, scenes and all other launcher file records are unchanged. No gameplay code or hosted player data was uploaded, and the service was not restarted.

Client **2026.10.06.4** is published and its exact manifest and both blobs have been downloaded and verified through the public HTTPS launcher endpoint. Manifest SHA256: `0fdd69cff001312a976becb59538704371fe4a8efdefa06796f48daab241f22c`. Before publication, the remote database received a consistent SQLite backup and passed integrity checks; previous code/configuration, service configuration, manifest and both previous blobs were saved in `/root/tio-before-crate-alpha-up473qkv`.

Evidence is in `reports/reservation-crate-alpha/`: `asset-verification.json`, `crate-alpha-comparison.png`, `deployment.json`, `deployment.log`, `https-release.json`, and `hosted-health.json`. The original crate scene/frame checks also passed four cases (`evidence/crate_visual_native.json`); these are native model checks, not graphical rendering checks. Hosted post-release health: service active, both gameplay ports listening, integrity `ok`, 162 accounts, zero checkpoints and pending settlement jobs, and unchanged server source hashes.

The decoded comparison shows the black rectangle removed and the original soft crate shadow restored. Graphical game-client validation of 2026.10.06.4 remains outstanding. Close the game and reopen TIO Launcher to install this resource update before checking the crates in battle.
