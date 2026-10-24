# Private website integration

The game remains authoritative for credentials and player saves. The website
keeps email, roles, sessions, news and its Argon2id password hash in PostgreSQL.
It never mounts or directly opens the game database. Existing game accounts and
the legacy client protocol remain unchanged.

`Browser → website backend → private adapter → Accounts / existing SQLite`

## Runtime and trust boundary

Run `python -m registration.game_bridge` with the existing `.venv-web` runtime
and `registration/requirements.txt` (Flask 3.1.3 and Waitress 3.0.2). The adapter
binds exclusively to **127.0.0.1:8081**. Every endpoint requires
`Authorization: Bearer <GAME_SERVER_API_KEY>`. Do not expose this listener in
nginx, publish its port, or forward it publicly. Run the website with host
network access if using Docker so its server-side requests can reach loopback;
bind the website's public-service listener to loopback as well. PostgreSQL must
remain on a private Docker network with no public port.

Install `deploy/tio-game-api.service`. Its protected configuration file is
`/etc/tio-server/game-api.env`, owned by `root:root` with mode `0600`; systemd
reads the file before running the service as `tio`. Configuration:

| Environment | Purpose |
| --- | --- |
| `TIO_CONFIG` | Existing `/etc/tio-server/server.toml` |
| `GAME_SERVER_API_KEY` | Random private secret of at least 32 characters |
| `TIO_GAME_API_KEY_FILE` | Optional alternative secret file, owned by `root:tio`, mode `0640` |
| `TIO_WEB_STATUS_FILE` | `/var/lib/tio-server/web-status.json` |
| `TIO_GAME_VERSION` | Optional documented emulator release label, set on the **game service** |

Create the key on the VPS in the protected environment file and supply the same
value to the website's protected environment as `GAME_SERVER_API_KEY`. Never
commit, print or place it in a frontend variable. Key rotation changes receipt
fingerprints, so finish/reconcile pending account operations before rotation.
The systemd service needs write access only to the existing game data directory.

Inspect the actual hosted code/configuration, create consistent SQLite backups
and archive the previous code/configuration before installing an update. Never
upload local saves. Reloading the adapter alone does not restart gameplay;
installing the runtime status publisher requires the normal game update procedure.

## API contract

All request/response bodies use UTF-8 JSON; request bodies are limited to 4 KiB.
Usernames preserve game restrictions: 3–32 lowercase ASCII letters, digits or
underscores. Passwords preserve game restrictions: 12–64 printable ASCII
characters without spaces. Russian interface/content remains unrestricted by
these credential compatibility rules.

`requestId` must be a new UUID or 16–128 ASCII letters/digits/hyphens/underscores.
Retry an interrupted operation with exactly the same ID and payload.

| Method/path | Request | Success |
| --- | --- | --- |
| `POST /v1/accounts/create` | `{username,password,requestId}` | 201 `{username,created:true,replayed:false}`; replay 200 with `replayed:true` |
| `POST /v1/accounts/find` | `{username}` | 200 `{username,exists:boolean}` |
| `POST /v1/accounts/verify` | `{username,password}` | 200 `{username,verified:true}` |
| `POST /v1/accounts/password` | `{username,currentPassword,newPassword,requestId}` | 200 `{username,changed:true,replayed:boolean}` |
| `GET /v1/status` | No body | 200 normalized server status |

Failures return only `{error:code}`. Codes are `unauthorized` (401),
`invalid_request` (400, or an HTTP routing/body-size status), `username_invalid`
(400), `password_invalid` (400), `username_exists` (409), `request_id_conflict`
(409), `invalid_credentials` (401), `rate_limited` (429), and
`service_unavailable` (503). Translate these in the website; do not show database
exceptions or internal endpoint details.

Creation preserves PBKDF2-HMAC-SHA256 with 600,000 rounds, individual random
16-byte salt and the existing account table. The additional `game_web_receipts`
table contains only request IDs, operation, username, keyed request fingerprint
and timestamp. Credential mutation and receipt insertion use one SQLite write
transaction. No plaintext password or gameplay data is returned/stored in receipts.
Creation does not create a character; new players use the actual game's onboarding.

Website registration should keep a pending PostgreSQL record and operation ID
until the adapter confirms provisioning. Retrying the same operation resolves an
unknown response without overwriting another account. An existing username can
be linked only after authoritative game password verification. Website login
verifies the game password and updates its separate Argon2id hash after success,
so legacy CLI password resets remain authoritative. Password changes use the
private endpoint, then update the website hash and invalidate website sessions;
an interrupted website update is reconciled on the next successful login.

## Real status

The game's `MultiServer` publishes an atomic aggregate snapshot every five
seconds from `server_population()`: exact unique authenticated accounts including
character selection and battles, maximum population, release label and timestamp.
Shutdown publishes offline state. No usernames, characters or saves are exported.

The adapter probes the actual login listener, caching the probe for ten seconds
to protect game connection budgets. A heartbeat older than 20 seconds, a missing
or malformed file, or an unavailable listener produces `playersOnline:null`,
never a fabricated zero. A fresh genuine zero is returned as zero.

Example:

```json
{"status":"online","playersOnline":2,"maxPlayers":16,"serverVersion":"unknown","observedAt":"2026-10-06T12:00:00+00:00","source":"emulator"}
```

`unknown` is the honest version default until the deployment sets a release label.
Website maintenance mode/messages are website settings; they should override the
public status without modifying the game's wire protocol. Cache the website's
normalized status endpoint for at least ten seconds. The private adapter caps
authorized requests at 60 per minute and simultaneous password work at two.

## Automated checks

```text
python -m unittest registration.test_game_bridge
python -m unittest discover -s tests -p test_multi_account.py
```

These validate API authentication, creation/retries/conflicts, game-compatible
passwords, legacy resets, character preservation, body/rate limits, real TCP
health checks and exact/stale status handling. They do not substitute for
validation with two graphical game clients on the hosted multiplayer service.


### Mailbox-authorized password recovery (2026-10-23)

`POST /v1/accounts/recovery` is private and bearer-authenticated, with exact
fields `{username,newPassword,requestId,provisioningId}`. Only the portal calls
it after consuming/validating mailbox proof under its credential lock. For an
ACTIVE account, provisioningId is empty and an existing game account is required.
For PENDING signup it is the original stable creation ID; an existing game
account must have that matching creation receipt. Unrelated legacy accounts
cannot be taken over. Credentials and receipt commit atomically; stale receipt
replay fails after an intervening change. Response:
`{username,changed:true,replayed:boolean}`. No public reverse-proxy route is added.
