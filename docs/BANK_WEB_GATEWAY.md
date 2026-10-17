# Stripe bank HTTP integration

The portal uses its existing ACTIVE session and verified `gameUsername` link.
It cannot choose an arbitrary save owner. The private adapter resolves a requested
character slot through `character_identities` and existing `characters`; it never
creates characters, resets wallets, or accepts an owner supplied by the browser.

`Browser → authenticated Next route → private loopback adapter → BankStore`

`Stripe → public raw webhook route → private loopback adapter → signed paid ledger`

## Runtime and configuration

`python -m server.bank_gateway` is an independent service, requiring no gameplay
runtime changes. It uses the existing `registration/requirements.txt` Flask and
Waitress environment and reads the existing `TIO_CONFIG` database location.
`multi_account=true` and an existing valid account database are mandatory.
Waitress binds only **127.0.0.1:8082**. Every route requires both a loopback TCP
peer and `Authorization: Bearer <BANK_SERVICE_KEY>`, compared in constant time.
The service does not trust forwarded peer headers. Never publicly proxy this
listener or its `/v1/bank/*` routes.

Prepared unit: `deploy/tio-bank-api.service`. Protected environment file:
`/etc/tio-server/bank-api.env`, `root:root`, mode `0600`. Set:

| Environment | Meaning |
| --- | --- |
| `TIO_CONFIG` | Existing `/etc/tio-server/server.toml` |
| `BANK_SERVICE_KEY` | New independent random secret, 32–512 characters |
| `TIO_BANK_MERCHANT_CONFIG` | Optional protected merchant JSON path |
| `STRIPE_SECRET_KEY` | Live merchant API key, once configured |
| `STRIPE_WEBHOOK_SECRET` | Signing secret for the configured Stripe webhook |

Protected merchant JSON `/etc/tio-server/bank-merchant.json` must be readable by
`tio`, e.g. `root:tio`, mode `0640`. It accepts only the following non-secret
configuration keys; the two Stripe secrets stay in the environment:

```json
{
  "enabled": false,
  "type": "stripe_checkout",
  "currency": "eur",
  "minor_units_per_gold": 1,
  "success_url": "https://ti-reborn.com/ru/bank",
  "cancel_url": "https://ti-reborn.com/ru/bank",
  "require_livemode": true,
  "minimum_gold": 50,
  "maximum_gold": 100000,
  "signature_tolerance_seconds": 300
}
```

This is a disabled configuration example, not merchant activation. The merchant
approved EUR tariff is €0.01 per Gold, with a minimum order of 50 Gold (€0.50).
The merchant must supply live keys and verify the EUR minimum for its settlement
currency before enabling purchases. Cryptocurrency payments are a later stage. Preserve `require_livemode=true` on the
hosted game. No payment or Gold is simulated if configuration is absent.
Return URLs can point to `https://<portal-origin>/ru/bank` or `/en/bank`; visits
and URL query parameters never grant currency. Charges use Stripe minor units,
including its currency-specific exceptions, per the
[Stripe currency documentation](https://docs.stripe.com/currencies).

The portal's existing protected `/etc/tio-portal/portal.env` receives only:

```text
BANK_GATEWAY_URL=http://127.0.0.1:8082
BANK_SERVICE_KEY=<same-private-service-key>
```

No `NEXT_PUBLIC_*` variables or merchant secrets are used. The gateway URL
validator permits only HTTP loopback origins without paths, credentials or query
parameters. Portal and gateway must share the host's loopback network, consistent
with the existing account bridge; a container's isolated loopback will not work.

Before installation, inspect actual hosted code/configuration, back up the live
SQLite database and previous service/configuration and preserve portal rollback
artifacts following `deploy/BACKUPS.md` and `docs/GAME_WEB_API.md`. Never upload
local databases. Install the new unit and protected configuration, run
`systemctl daemon-reload`, then start `tio-bank-api` independently. The portal
must be rebuilt and installed through its existing standalone release procedure.
Next's standalone output can copy local `.env*` files during tracing. Exclude
every such file from the release archive, as the existing portal installer
requires; configuration must come only from the protected host environment.
No installation or deployment was performed by this implementation task.

## Public routes and trust boundaries

| Method/path | Authorization and body |
| --- | --- |
| `GET /api/bank/status?slot=1` | Existing ACTIVE linked session; owned slot 1–5 |
| `POST /api/bank/orders` | Existing Origin + session CSRF + linked session; strict `{slot,gold,requestId}` |
| `GET /api/bank/orders/<uuid>?slot=1` | Linked session; exact order owner and character slot |
| `POST /api/bank/stripe/webhook` | Stripe signature; exact raw body, maximum 256 KiB |
| `GET /ru/bank`, `GET /en/bank` | Existing linked session; otherwise localized login redirect |

Prepared nginx include `deploy/tio-bank.nginx.inc` forwards those API routes to
the existing **Next listener on 127.0.0.1:3000**, including the exact webhook
location before the 4 KiB ordinary bank API prefix. Include it inside the
existing TLS portal vhost after checking actual locations; run `nginx -t`
before reload. Bank pages continue through the existing portal root location.
Preserve certificates, ACME, downloads and launcher updates. Do not rewrite or
deserialize webhook JSON in nginx or another middleware.

Create the Stripe webhook endpoint at:
`https://<portal-origin>/api/bank/stripe/webhook`, subscribed to
`checkout.session.completed` and `checkout.session.async_payment_succeeded`.
Use the live endpoint signing secret. The public relay does not require browser
cookies or CSRF; its private hop requires the service key and `BankStore`
validates Stripe HMAC over the unchanged bytes. The backend accepts only a live,
paid, one-time Checkout session matching the existing server order's UUID,
session, amount, currency and metadata. Unpaid events never credit Gold.
Repeated paid events and repeated browser order requests use durable SQLite
receipts and do not create duplicate currency. Provider requests run outside
gameplay transactions. Storage failures return 503 so Stripe can retry.

Orders and status are never cached. Replies exclude save-owner aliases, provider
session IDs, keys and database details. A configured checkout response uses an
actual `https://checkout.stripe.com` URL. Gateway unavailability or missing
merchant configuration leaves the localized bank page usable with purchase
controls disabled. The browser saves the order request identity before IO and
reuses it after interrupted responses; changing quantity creates a distinct
order intentionally. It retains the last returned order for explicit status
checks after returning from Stripe. No browser data authorizes settlement.

The authoritative payment behavior follows
[Stripe Checkout creation](https://docs.stripe.com/api/checkout/sessions/create)
and [Stripe webhook delivery](https://docs.stripe.com/webhooks).

## Gameplay integration hooks

The HTTP gateway settles payments immediately into the existing wallet. Gold
beyond the uint32 wallet capacity remains in `bank_gold_payables`; it is never
discarded. Add the following to the game-owned wallet refresh/spend path, inside
the existing transaction and **before** selecting the wallet for serialization:

```python
if db.execute("SELECT 1 FROM sqlite_master WHERE name='bank_gold_payables'").fetchone():
    from tio.bank_economy import collect_paid_gold
    collect_paid_gold(db, save_owner)
credits, gold = db.execute(
    'SELECT credits,gold FROM wallets WHERE account=?', (save_owner,)).fetchone()
```

Here `save_owner` is the authenticated session's already resolved character
owner, never a login supplied by a client packet. Existing gameplay journal/
transaction rules must cover both collection and outgoing wallet projection.
Run collection after a Gold debit as well when capacity has just become free,
then reload the wallet before sending it. The read-only web status endpoint
reports both current Gold and any remaining payable without mutating the wallet.

Add a normal account-page link to `/${locale}/bank` in the root-owned portal
integration. The original client's bank button can open the same authenticated
browser page with an optional `?slot=1..5`; do not put a password, PIN or service
key in its URL. Browser login/link ownership remains required. These hooks are
integration contracts; shared runtime/account/native-client files were not
modified by this package.

## Verification

Run gateway checks using the existing Flask runtime:

```text
data/registration-check-env/Scripts/python.exe -m unittest tests.test_bank_gateway tests.test_bank_economy -q
```

On the host use `.venv-web/bin/python` instead. From `web/`:

```text
node node_modules/tsx/dist/cli.mjs --test tests/bank.test.ts tests/portal-routes.test.ts
node node_modules/typescript/bin/tsc --noEmit
node node_modules/next/dist/bin/next build --webpack
```

Checks cover two real SQLite account records plus a separate owned character,
HTTP/service authentication, ownership isolation, CSRF, signed raw callbacks,
prepayment state, retry/duplicate safety, transaction rollback and disabled
configuration. Provider IO uses explicit test fixtures; no merchant API key,
real charge, hosted deployment or graphical game-client payment was tested.
Before activation, verify the configured live merchant terms and webhook through
the normal release process; a production build alone is not payment acceptance.
