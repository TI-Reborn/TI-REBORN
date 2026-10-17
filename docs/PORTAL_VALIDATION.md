# Portal acceptance and hosted verification

The portal has separate acceptance boundaries: automated unit/integration checks,
hosted HTTPS/API checks, browser/mobile visual checks, and real graphical game
clients. Report each boundary separately; passing HTTP or legacy TCP protocol
tests does not prove two real graphical clients work.

## Hosted black-box checker

`tools/verify_portal_hosted.py` uses Python's standard-library HTTPS client and
system trust store. It never disables certificate verification. It visits both
language variants of Home, Register, Login, Download, FAQ, News, Changelog,
Community, How to Play, Maintenance, Account redirects and a genuine missing page.
It checks UTF-8/Cyrillic output, visible translation keys, document language,
titles/descriptions/Open Graph metadata, canonical and alternate-language links.
It also checks browser-language selection, cookie precedence, CSRF/origin
rejection, real status normalization and public download/news APIs.
The 32 default checks include a published news article and a missing news slug
in each language, plus an unknown dotted Russian route. Missing articles must
return 404 from both the API and HTML page; the HTML must contain the localized
404 screen with the correct document language, rather than an empty error shell.

Read-only default (rejected CSRF requests cannot provision accounts):

```powershell
python tools/verify_portal_hosted.py --base-url https://185.184.42.88 --report reports/portal/hosted-readonly.json
```

Creating fixtures requires explicit `--allow-create`. The script generates fresh
`webqa_*` usernames, example.invalid emails and random passwords. It changes only
those owned fixture accounts, retaining them for auditability. It never uses
existing players' credentials, changes player saves, creates game characters or
grants administrator roles. No fake forwarded IP headers bypass rate limits.

The `--allow-create` workflow below describes the legacy immediate-provisioning
mode. With mandatory email verification, its example.invalid mailbox cannot
complete proof and its new fixture remains PENDING without a game account.
Use read-only checks or existing ACTIVE fixtures on the live portal. Validate
the new signup flow with an owned real mailbox and interactive browser; never
disable production email or CAPTCHA requirements to accommodate the checker.
The current workflow and rollout are in
[email verification operations](../web/docs/EMAIL_VERIFICATION.md).

```powershell
python tools/verify_portal_hosted.py --allow-create --game-probe --credentials-file data/portal-qa-credentials.json --report reports/portal/hosted-full.json
```

With one fixture, registration consumes **four** attempts: one successful
registration, duplicate username, duplicate email and an invalid password.
`--accounts 2` consumes five attempts. These match the production five-per-hour
IP budget; avoid another mutating run from that IP within the same rate window.
The checker does not reset or evade production limits. Turnstile-enabled
production registration requires interactive browser testing and cannot be
bypassed by this script.

The authorized run verifies automatic session creation, duplicate errors, secure
host-prefixed HttpOnly/SameSite cookies, wrong/right passwords, EN/RU account
pages, normal-user admin API denial, password change, old-password rejection,
new-password login and logout. It does not possess administrator credentials.
Authorized news create/edit/publish/delete and settings changes therefore need a
separate administrator test using a concrete reversible fixture news article.
For email-gated signup, check a restricted PENDING session first, durable email
proof with the original password second, then ACTIVE access and game-account
creation. Opening a link, entering a wrong password and replaying a consumed
token must not provision an account.

Run automated email/game-bridge integration against disposable PostgreSQL and
local SMTP/game fixtures, preserving previous evidence:

```powershell
python tools/test_portal_isolated_postgres.py --report-dir reports/email-verification
```

The optional report directory contains sanitized `website-tests.log` and
`website-tests.json`. Relative paths use the repository root; the default path
remains `reports/site-backups`. Passing this suite proves its isolated backend
checks, while real Resend delivery and hosted graphical client behavior require
their separate validation.

To diagnose authentication after the creation budget is used, explicitly reuse
the protected fixture file. This mode creates no accounts, does not repeat
registration errors, and does not change passwords:

```powershell
python tools/verify_portal_hosted.py --base-url https://ti-reborn.com --existing-credentials-file data/portal-qa-credentials-20261006.json --auth-only --report reports/portal/hosted-auth-recheck.json
```

Remove `--auth-only` to include the public read-only checks. The saved file's
origin must match `--base-url`, and only owned `webqa_*` fixtures are accepted.
Keep the original full report as historical evidence and write targeted reruns
to separate report files. Failures include a check reason and expected/actual
statuses or booleans; credential values and complete response bodies stay excluded.

Optional `--game-probe` reuses existing emulator protocol helpers to authenticate
the generated accounts, reach an empty character-selection screen and observe
the real public online counter while connected. It does not enter a world,
create characters or perform gameplay. The legacy game's ORANGE transport is
not TLS; only disposable QA secrets are used. This is protocol integration,
**not graphical client validation**.

The JSON report contains check names, outcomes, HTTP statuses, aggregate counts
and sanitized failure class names. It excludes passwords, emails, usernames,
cookies, CSRF tokens and full server response bodies. Credentials are saved only
when `--credentials-file` is explicitly supplied, with mode `0600`, under ignored
workspace `data/` or `/root` on Linux. On Windows, restrict the file ACL to the
owner and SYSTEM, with inheritance disabled; `chmod` alone does not establish
that boundary. Choose a fresh filename: existing files are
never overwritten. Keep this file protected and remove it when no longer needed.
The report does not itself contain credentials or the credential-file path.

## Browser and localization review

Check both EN/RU versions on desktop, tablet and mobile. Confirm the menu opens
with keyboard/touch, focus remains visible, all form labels/errors are localized,
password buttons show pending state, and language selection survives reload and
reopening the browser. The HTTP checker validates locale-cookie precedence;
it cannot execute the language selector's browser JavaScript.

Verify layouts, imagery, reduced-motion handling, contrast, no horizontal
overflow, readable news text, link-disabled states for unconfigured communities,
real download availability and installation instructions. Inspect 404, error
boundary and maintenance screens in both languages. Do not intentionally break
the production service to trigger a 500 screen; exercise that case locally.

The API intentionally returns stable machine error codes. Confirm every emitted
code exists in both dictionaries and that the forms translate the code before
showing it. In addition to routing checks, exercise validation feedback in both
languages using invalid username/email/password and mismatched confirmation.

## Real hosted game clients

Use two real accounts from two graphical game clients on the deployed service.
Confirm website registration credentials work in the native client and launcher,
account switching preserves each player's characters/progression, a website
password change allows the new password and rejects the old one, and player
counts increase/decrease correctly. Complete normal login, shared multiplayer
interaction and reconnect checks without substituting bots or local demos.

Keep deployment backups and previous code/configuration available. Validate
`tio-server`, `tio-game-api`, website, PostgreSQL and nginx independently; preserve
the existing update manifest and launcher download paths during nginx changes.
