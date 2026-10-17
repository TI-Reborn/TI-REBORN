# Original-resource avatars — 2026-10-12

## Generated portraits — 2026-10-13

Hosted client release `2026.10.13.2` adds six original generated portraits:
Veteran, Scout, Ranger, Medic, Combat Dog and Miner (IDs10007–10012).
These are free and appear in **Gallery → Ordinary**. The catalog's category byte
is not an ownership flag: the original reader routes0 to Ordinary and1 to Premium.
Legacy IDs10001–10006, their exact images and existing saved selections remain
valid. New64×64 JPEGs are1959–2181 bytes, below the native4096-byte limit.
The released DLL's FC whitelist changes exactly one byte to accept IDs through10012.

Six original PNGs and exact built-in image_gen prompts are in
`assets/generated-avatars-v1`. Preview and evidence are in
`reports/generated-avatars-20261013`. Nine avatar tests passed locally;75 avatar,
shared-arena and recovery tests passed in an isolated copy of actual hosted code.
Automated native checks cover Ordinary category routing, the Install button,
all12 images/CRCs, assignments and relocation. GUI/GPU/file loading are stubbed;
this does not claim validation with actual graphical game clients.

Deployment backed up the actual hosted database, previous code/config/service and
client manifest/DLL to `/root/tio-before-generated-avatars-j29ir1rv`.
All database rows were preserved and the service is active. No hosted QA accounts
or clans were created. Close the game and update through the launcher to receive
the portraits and the expanded client reader.

Published on the authoritative multiplayer server with client2026.10.12.4. Backup: /root/tio-before-avatar-types-114fxa5o. All hosted rows were preserved. No test accounts or clans were created in the live database.

The original client has a silhouette atlas and six tutorial acknowledgement images. Three are suitable for the initial catalog: Raider portrait and two Spectra Crystals logo variants. Version2026.10.12.4 adds the original female silhouette from pda/avatars.PNG and dog/miner portraits from pda/ts_npc_icons.png. Women use the silhouette; no original female face portrait was recovered. The dog/miner portraits are derived from the original HUD icons. The full historical user-avatar catalog was downloaded from the original server and is absent from installed resources. This new free emulator catalog uses original artwork, IDs10001–10006 and price0; those IDs and the price are emulator choices. Each64×64 JPEG fits the original4096-byte transfer limit. Original source hashes, image bytes and native CRC32 compatibility are checked.

The native avatar window uses AC01 list, AC02 image, AC04 purchase and AC05 assignment. Responses AC08 and AC06 reach original readers. All three images are available immediately, with no charge. Upload/admin edits are rejected. Selection requires an owned fighter of supported type1–6 and an idle city session, with durable travel/battle/prison guards checked under the shared hub lock. Identity comes from the authenticated session. Durable choices use pet_avatars(account,pet_id,avatar_id); wallets, PetInfo66, inventory, names and3D appearance are preserved. Assignment is idempotent and ID0 restores the default.

FC/v1 wraps the exact current rain receiver. Layout: opcode, version1, u16count, repeated u32actorId/u32avatarId; count≤31 native actor slots. Invalid data cannot partially update actors. The city heartbeat resends account-local IDs after loading. City synchronization is disabled in battles/lobbies, where IDs differ. Shared scenes freeze saved choices under global actor IDs, and only visible actors receive assignment snapshots. Choices survive checkpoints. Room25 portraits also use saved IDs. The existing squad-avatar toggle controls list display. Browser services V2 retain their disabled historical paid-avatar catalog; this release implements the native game window.

Validation: eight focused local SQLite/gate/ownership/privacy tests;74 tests on an isolated copy of current hosted code; an isolated two-account shared match with different saved portraits, global ID mapping and visibility checks; x86 assignment at two ASLR bases, original AC08/AC06 readers and original CRC32. GUI/GPU/file-cache operations are stubs; real graphical clients have not been verified. Actual source hashes, read-only requests for two saved accounts, SQLite integrity, all13 accounts, zero service restarts, trusted TLS on29512/29513 and trusted HTTPS manifest plus all four release files passed.

Reports are in reports/avatars: client-native.json, resource-proof.json, remote-tests.json, shared-avatar-integration.json, deployment.json, hosted-verification.json and https-verification.json. Tools: build_avatars.py, verify_avatars_native.py, deploy_avatars.py. Prepare from fresh hosted source/DLL/manifest bytes and preserve line endings. Never publish local saves over hosted data. Close the game and update through the launcher before using the native avatar window.

The expanded catalog permits avatars for female resource2, dogs3/4/5 and miner6. City snapshots now include nonhuman pets. Existing IDs1–3 and saved choices stay valid. The client whitelist expansion changes exactly one byte of the verified published DLL; the rest of the reader chain and all original handlers stay unchanged. Native catalog/image/CRC checks cover all six images and ASLR tests cover all three new IDs plus rejection of ID10007. Actual hosted read-only snapshots were checked for10 saved owners, including6 nonhuman pets; all13 accounts and all database rows were preserved. No actual graphical client playback was performed.
