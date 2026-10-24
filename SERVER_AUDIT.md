# Server deployment audit — 2026-09-21

## Latest live result — is*hosting VPS

User confirmed original ti.exe connected to 185.184.42.88:28512, selected
ProbeNew, entered the city and started a training battle. Screenshot shows
multiple turns and VPS city_session_started at 14:25:26 UTC. Both connection
fixes below are deployed. This run used direct ti.exe startup with CFG address
changes, not the instrumented launcher. Ubuntu preflight, public TCP handshake
and clean systemd restart were also observed. The earlier stock-client-entry
blocker is resolved for this single diagnostic account on this installed client.

User subsequently confirmed credits and squad state persisted after the
requested service restart and repeat login. Basic single-account deployment,
native-client battle entry and persistence acceptance checks are now complete.
Full client feature compatibility and multi-account operation are not established. Historic
PARTIAL/untested statements below describe earlier stages, not this new result.

## Scope and readiness

The existing game server is `tools/loopback_exchange.py:LoopbackExchange`.
`tools/run_reservation.py` starts the Windows client through
`probe_item_fixture.py` and `capture_loaded_orange.py`; it is NOT a Linux server
entry point. The deployment entry point added in this task is `python -m server`.
It reuses LoopbackExchange and the existing game services, not a new protocol.

**PARTIAL readiness:** the backend can run separately, but the existing login is
diagnostic, single-account and sequential. A stock-client remote city entry has
not been demonstrated. No multi-user production readiness is claimed.

## Network

Before this task: `socket.socket()` (IPv4 TCP), bind `127.0.0.1:0`, OS-selected
ephemeral port, backlog 1. Login and game use TWO sequential TCP connections to
the SAME listener. S2C 06 advertises `127.0.0.1` and that ephemeral port.
No UDP sockets are used by the server.

Installed client `base/autoexec.cfg` contains `orange_addr 139.162.160.97` and
`orange_port 28512`; `base/config.cfg` also contains `orange_port 28512`.
`base/serverlist.cfg` contains `<New Mexico> gameserver` (a label, not an IP).
28512 is thus a verified client configuration value, NOT the old emulator's
fixed port. The new standalone configuration uses TCP 28512 by default.

`tools/capture_loaded_orange.py` hardcodes loopback in its Winsock allowlist and
native connect call. Editing client CFG files cannot override that diagnostic
path. It remains unchanged, as launcher work is explicitly out of scope.

## Persistent data

Existing save: `data/reservation.sqlite3`. Account identity is the hardcoded
`probe_user`; password validation is `probe_password`. There is no account
registration table, password-hash store or Account API. The standalone wrapper
does not invent one. Restrict its port to the operator's IPv4.

SQLite is the sole player storage. `characters` stores character slots/names;
`owned_pets` stores pet and inventory protocol snapshots, including equipment,
health and progression. Additional tables managed by `tio/` stores hold wallets,
warehouse, learned abilities, proficiency, ranks/settlement, achievements,
rental deadlines, templates, recovery clocks, travel, mining currency and range
admissions. Copy the WHOLE SQLite database, never selected tables. Schema setup
is the existing CREATE TABLE/compatibility logic; no new save migration.

Standalone production data directory: `/var/lib/tio-server`;
database: `/var/lib/tio-server/reservation.sqlite3`.
Application files belong in `/opt/tio-emulator`; configuration in
`/etc/tio-server/server.toml`. Updates must not replace `/var/lib/tio-server`.
Live battle objects/rooms are in memory, not resumable snapshots. Shutdown uses
the existing disconnect/forfeit settlement; stop in the city when possible.

## Linux dependencies and files

Runtime services use Python stdlib (socket, threading, sqlite3, zlib, XML, JSON).
Standalone TOML parsing requires Python >=3.11; Ubuntu 24.04 provides 3.12.
No Frida, PE parser, Unicorn, Windows DLL or graphical environment is required
by the server runtime. Research extras in pyproject.toml remain dev-only:
pefile, capstone, unicorn, frida.

Required runtime: `server/`, all `tio/**/*.py`, `config/*.json`, and these tools:
`loopback_exchange.py`, `survival_scene.py`, `battle_actor_fixture.py`,
`battle_roster_fixture.py`, `mining_scene.py`, `shooting_range_scene.py`.
Despite their names/location, these scene helpers are game runtime dependencies.
Required evidence assets: `items_diagnostic.xml`, `skills_diagnostic.xml`,
`zones_diagnostic.xml`, `owned_pet_trial.json`. Their relative names/case must
be preserved. Imported map geometry already lives in JSON; server does not read
the installed client assets. Clients still need their matching game resources.

Dev-only: `tests/`, native verification/probe/import/build/trace tools, captured
DLLs/binary memory dumps, logs/screenshots and other research evidence. Do not
upload the entire evidence directory or the Windows game installation.
The deployment packager includes an explicit runtime allowlist.

## Windows-specific boundary

`probe_item_fixture.py`: hardcoded `C:\Program Files (x86)\TIOnline`, tasklist,
temporary client catalog/scene changes. `capture_loaded_orange.py` and JS hooks:
Frida, Winsock, kernel32/user32, original x86 exports and callbacks. These run
on the Windows client only and are excluded from the standalone server.
Server runtime paths already use pathlib and project-relative assets. Wire
resource basenames/backslashes are client protocol conventions, not Linux paths;
they must not be globally rewritten.

## Remaining client limitations

Native normal-login credential transformation, character creation/selection and
loader behavior require an end-to-end stock-client check. Current handshake
accepts only the diagnostic account/profile and character slot 1. Compatibility
hooks also supply treatment/enhancement settings and several UI fixes. Opening
a public socket does not remove these dependencies. See CLIENT_CONNECTION.md.

## Validation boundary

Windows host has no installed WSL distribution/Linux runtime. Automated tests
cover server imports, TCP bind/handshake, advertised IPv4, sequential sessions,
stop and SQLite persistence. Ubuntu/systemd, SIGTERM delivered by systemd and
original-client public-IP gameplay must still be verified on the VPS.

## Completed automated checks

2026-09-21: `python -m unittest discover -s tests -q` — **519 tests PASS**,
30.582 seconds (513 existing + 6 deployment tests). Local log:
`data/deployment-tests.log` (not included in deployment bundles).

New tests exercise actual TCP sockets on 0.0.0.0, both handshake stages,
configured advertised IPv4/port, shared XML delivery, character creation,
city entry and ping using a Python protocol peer. They purchase two knives,
wait for the existing achievement payout, stop with a connected client,
restart, log in again and verify wallet/inventory plus SQLite integrity.
This is NOT a substitute for testing the original Windows client.

Also verified: idle stop, repeated sessions on the same listener, SIGINT and
SIGTERM handlers using signal.raise_signal (not Linux OS-delivered signals),
read-only preflight, relative path resolution, safe SQLite backup and overwrite
refusal. The 161-file runtime archive was extracted to a temporary directory;
`python -S -m server --check` passed there, with site-packages disabled.
A fresh virtualenv installed requirements.txt and passed preflight. All server/
and tio/ source parsed under Python 3.12 syntax rules. Execution was on Windows
Python 3.14, NOT an Ubuntu 3.12 runtime. WSL reports not installed.

## Files changed in this task

- Existing: `tools/loopback_exchange.py` — optional persistent listener and
  advertised IPv4, bounded game-connection wait, stop-aware accept, optional
  trace output and quiet mode. Existing local constructor defaults preserved.
- Added: `server/__init__.py`, `server/__main__.py`, `server/config.py`,
  `server/runtime.py` — standalone configuration/preflight/service lifecycle.
- Added: `config/server.toml`, `requirements.txt`.
- Added: `deploy/tio-server.service`, `deploy/FIREWALL.md`,
  `deploy/package_server.py`, `deploy/backup.py`, `deploy/check_connection.py`.
- Added: `SERVER_AUDIT.md`, `DEPLOY_HETZNER.md` (now `DEPLOY.md`), `CLIENT_CONNECTION.md`.
- Added: `tests/test_server_deployment.py`.

No launcher, game executable, client CFG, live player database, Account API,
game packet format or gameplay rules were changed by this task.

## VPS verification and first native-client correction

Deployment continued on is*hosting Ubuntu 24.04 x86-64 (185.184.42.88).
User screenshots confirm preflight, systemd active/enabled, listener on
0.0.0.0:28512 and successful SIGTERM restart. Remote challenge probe succeeded.
Client CFG addresses were subsequently backed up and set to this VPS.
Stock-client log shows login type0 followed by game type1; VPS then reported
Linux ENOTCONN (107). The deployment accept guard queried getpeername() on the
login socket after the client disconnected it. Fixed by caching the peer IPv4
on accept. Integration login now closes its login socket before mode1 connects.
The corrected file still needs uploading/restarting on VPS and native retest.

Native retest then confirmed second_connection_accepted and the character
selection screen. The next disconnect occurred after the inherited 5-second
automatic-probe response deadline. Standalone server/character/create UI waits
now allow 300 seconds and reply to existing 70/9E keepalives; automatic handshake
deadlines and local probe defaults are unchanged. Regression test deliberately
waits 5.5 seconds at character selection, pings, then enters the city and verifies
persistence. This UI-wait correction still needs uploading to the VPS.
# Дополнение: независимые аккаунты (2026-09-21)

Опциональный `multi_account=true` использует `server/multi.py` и
`server/accounts.py`: отдельные аутентифицированные сессии и сохранения,
TCP game_port (28512) для входа и TCP session_port (28513) для игры.
UDP отсутствует. Учётные данные хранятся в новой таблице accounts той же
reservation.sqlite3, пароли — PBKDF2-SHA256 с солью. Данные probe_user сохраняются.
Установка и ограничения: MULTIPLAYER.md. Общих PvP-комнат на этом этапе нет.

## Дополнение: присутствие и городской чат (2026-09-22, локальная сборка)

`server/presence.py` объединяет список персонажей по локации, маршрутизирует
чат и выдаёт публичный профиль по имени. Профиль читает SQLite без записи;
кошельки, инвентарь и учётные данные в ответ не входят. Оригинальные C7,
21/22 и 68/A7 обработчики исследованы, чтение пакетов проверено в Unicorn
с явно обозначенными заглушками UI/строк. См. `evidence/social_native.json`.

Карточка реализована частично: уровень и сводка сохранённых результатов
в «О себе». Исторический онлайн, официальные рейтинги и детальная таблица
бойцов не восстановлены. Список и чат требуют проверки двумя оригинальными
клиентами после установки; сам VPS в рамках этой работы не изменялся.
Политика каналов, границы реализации, установка и откат: `CITY_SOCIAL.md`.
