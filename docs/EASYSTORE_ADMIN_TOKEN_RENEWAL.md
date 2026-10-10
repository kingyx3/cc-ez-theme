# EasyStore admin JWT renewal (dev / prod)

The undocumented EasyStore Admin API operation POST
https://api.easystore.co/admin/v2/me/stores/auth with a store_code in its
JSON body and a valid **store-scoped** JWT was observed to issue a fresh
store-scoped JWT expiring approximately 30 days later. EasyStore also issues
**user-scoped admin JWTs** (no `sid`) before a store is selected; the renewal
script can exchange these once for a store-scoped token as a bootstrap. A
non-JWT public API access token or a copied `Bearer ` prefix is not supported. A second request using
that new token also worked with browser cookies omitted. A GitHub-hosted
runner still needs to be verified by a manual dry run. EasyStore could change
or revoke this behavior.

## Getting the right token (seeding or reseeding)

Renewal can only extend a session EasyStore still accepts; it cannot sign in
(login needs reCAPTCHA and possibly OTP). Seed each environment once, and
reseed only if the workflow reports the session itself is rejected:

1. Sign in at https://admin.easystore.co with **Keep me signed in** ticked and
   open the store this environment belongs to (dev or prod).
2. Open the browser DevTools console on that tab and run
   `copy(localStorage.getItem("_easystore_session"))`. This copies the admin
   session JWT, which EasyStore's own admin app sends as `Authorization:
   Bearer` to `api.easystore.co`. Do **not** use `_easystore_app_token`: that
   one is for `apps.easystore.co` and the admin API rejects it with HTTP 401.
3. Paste it into that environment's `EASYSTORE_ADMIN_TOKEN` secret (no
   `Bearer ` prefix), then close the tab without clicking **Log out**, and do
   not use "Log out from all other devices". Inferred from the admin app's
   behavior: logging out ends the session server-side, which would invalidate
   the copied token.
4. Dispatch the workflow for that environment with dry_run=true, force=true,
   then dry_run=false, force=true. From then on the daily run renews it.

## Configure dev and prod separately

In GitHub Settings → Environments, configure these items **in each environment**,
with values belonging only to that environment:

| Item | Scope | dev | prod |
| --- | --- | --- | --- |
| EASYSTORE_ADMIN_TOKEN | Environment secret | Dev store-scoped JWT | Prod store-scoped JWT |
| EASYSTORE_STORE_CODE | Environment variable | Dev store code | Prod store code |
| EASYSTORE_STORE_DOMAIN | Environment variable | Dev store URL or bare hostname | Prod store URL or bare hostname |
| EASYSTORE_POD_ID | Environment variable | Dev pod ID | Prod pod ID |
| EASYSTORE_ROTATION_GH_TOKEN | Environment secret | GitHub environment write credential | GitHub environment write credential |
| EASYSTORE_MCP_WORKER_NAME | Optional environment variable | Unset unless using a separate dev Worker | Set to cc-easystore-admin-mcp if prod owns this Worker |
| CLOUDFLARE_API_TOKEN | Environment secret, when Worker configured | Dev Worker token | Prod Worker token |
| CLOUDFLARE_ACCOUNT_ID | Environment secret, when Worker configured | Dev account ID | Prod account ID |

The current Admin MCP Worker is prod-specific. **Do not point dev at the
prod Worker.** The Worker receives an updated EASYSTORE_ADMIN_TOKEN binding
through Cloudflare's single-secret API without redeploying code.

The workflow uses environment: matrix.deployment_env and independent
concurrency groups. Scheduled runs start one isolated job for dev and one
for prod. A manual dispatch chooses exactly one, defaulting to dev. Its
script verifies the selected job environment matches the target environment.
There is **no fallback to a repository-level JWT** and no cross-environment
copy of tokens or store codes.

## GitHub permission and credential setup

The ordinary GitHub Actions GITHUB_TOKEN cannot update Actions environment
secrets. Configure EASYSTORE_ROTATION_GH_TOKEN independently in each
environment using a **fine-grained PAT** scoped to this repository with
**Environments: read/write** permission. Rotate that PAT before its own
expiry. A GitHub App installation token is also suitable, but installation
tokens are short-lived and must be minted per run: do not save a static
installation token as an environment secret.

The script invokes the GitHub CLI to set EASYSTORE_ADMIN_TOKEN using
--env dev or --env prod, as selected, with the new JWT on **stdin**. It
never puts the token in CLI arguments, workflow step outputs, files or logs.
The workflow's default GITHUB_TOKEN is restricted to contents: read.

For Cloudflare synchronization, configure EASYSTORE_MCP_WORKER_NAME only
on the environment owning that Worker. Its associated Cloudflare API token
needs Workers Scripts Write permission. If the Worker is configured but
Cloudflare credentials are missing, the job fails before renewal.

## Activate and verify

1. Merge the PR, then configure/verify all environment-scoped values.
2. Manually dispatch Renew EasyStore administrator tokens on main for
   **dev**, dry_run=true and force=true. This performs a real token
   exchange and a read-only admin theme-list verification, but does NOT
   change GitHub or Cloudflare secrets.
3. Repeat the dry run for **prod**.
4. Manually dispatch for dev, dry_run=false and force=true, then repeat
   for prod. Check the named environment secret's updated timestamp in
   GitHub Settings. If the prod Worker is configured, verify an MCP
   read operation afterward.
5. GitHub Actions runs daily at 03:17 UTC (11:17 Singapore time) for dev
   and prod independently. Every run checks the stored token against the
   read-only admin themes API. The secret is renewed when its **GitHub
   environment secret last-updated timestamp** is 14 days old, or earlier
   when its JWT is within 14 days of expiry, no longer authenticates,
   or still represents an account-scoped rather than store-scoped session.
   A healthy recent token is left unchanged.

The script verifies that the returned JWT is different, has the same
store identity (sid), and works against the admin theme-list API before
updating secrets. Where both JWTs have numeric expiry claims, it also
requires sufficient validity extension. The public EasyStore
access token is never used for this exchange.

Updates to the Cloudflare Worker happen **before** GitHub secret replacement,
so a failed GitHub update leaves the prior GitHub JWT due for renewal on
the next run. A failed job is visible in Actions; configure workflow-failure
alerts. If a token has expired or been revoked, recover by manually
reauthenticating in EasyStore and setting the correct environment's secret
(and its Worker secret if applicable). The workflow does not bypass MFA,
CAPTCHA, or attempt login with a saved account password.

These renewable credentials are effectively long-lived admin credentials.
Restrict environment access and never paste JWTs into logs, PRs or issues.

## Troubleshooting GitHub Actions

If the job fails with `EASYSTORE_ADMIN_TOKEN is not a three-part JWT`,
the selected environment contains a non-JWT value (or the word `Bearer`).
Confirm you copied **only** the administrator session JWT from EasyStore,
not `EASYSTORE_ACCESS_TOKEN` or `app_token`. Do not paste its value into an
issue, log, or chat. Update **only the failed environment's**
`EASYSTORE_ADMIN_TOKEN` secret.

If the JWT is user-scoped, the workflow will bootstrap it to a store token by
calling `/me/stores/auth` with that environment's `EASYSTORE_STORE_CODE`;
the result must be store-scoped and pass the admin theme-list check before
the secret can be updated. An expired JWT still requires a normal EasyStore
login. A forced `dry_run=true` call exchanges and checks a token but does not
persist a replacement.

`EASYSTORE_STORE_DOMAIN` may be configured as a bare domain or as a standard
HTTPS URL ending in `/`. The script normalizes it to the hostname required
by EasyStore's routing header. It rejects non-HTTPS URLs, paths and query
parameters so the wrong store cannot silently be selected.

## Legacy administrator JWT without a standard expiration claim

A dev dry-run may report that `EASYSTORE_ADMIN_TOKEN` has no valid JWT
expiry. JWTs that **omit** `exp` or use a nonnumeric expiry may still be accepted by EasyStore.
The renewal script can exchange these credentials without assuming an
indefinite lifetime. A replacement lacking `exp` is permitted only when the
input token also lacks a valid numeric expiry; the replacement must be
different, preserve the store identity, and successfully authenticate to a
read-only EasyStore admin API before any secret update.

A missing or malformed input `exp` cannot establish how many days remain.
The scheduling decision therefore uses GitHub's environment secret
`updated_at` timestamp instead of attempting to guess an expiry. An
invalid/expired upstream credential will fail at the EasyStore exchange.
The workflow never prints JWT payloads. On continued failures, replace only
the failing environment's `EASYSTORE_ADMIN_TOKEN` with its own valid EasyStore
admin session JWT, then perform a forced dry run before enabling live writes.

## When the exchange is rejected (HTTP 401/403)

Failures include EasyStore's machine error code when it has one, for example
`HTTP 401 (invalid_access_token)`; messages and bodies are never printed.
On a 401/403 from the exchange, the script makes one read-only
`GET /admin/v2/me/profile` call with the same token and says which case it is:

- **Session rejected too**: the stored token is revoked, expired, or not the
  `_easystore_session` value. No code change can fix this; reseed as above.
- **Session still valid**: only the exchange for this store was refused. Check
  `EASYSTORE_STORE_CODE` and that the signed-in account can access that store.

## Distinguishing EasyStore upstream failures

On GitHub-hosted runners, the first API call exchanges the environment-scoped
admin JWT with `POST /admin/v2/me/stores/auth`. The second call verifies the
replacement JWT using the read-only admin theme listing. Failures now report
**only** the failing operation and the numeric HTTP status; upstream error
responses, URLs, tokens and headers are never printed.

- `EasyStore token exchange returned HTTP 401/403`: EasyStore rejected the
  selected environment's input credential. Make sure
  `EASYSTORE_ADMIN_TOKEN` is the actual administrator session JWT from the
  **matching environment's** EasyStore account, not the public API access
  token, a token from the other store, or a JWT with a `Bearer ` prefix.
- `EasyStore token exchange returned HTTP 400/404`: Check the matching
  environment's `EASYSTORE_STORE_CODE` and whether EasyStore still supports
  the undocumented exchange endpoint. Do not assume changing JWT expiry
  validation will fix an upstream rejection.
- `EasyStore admin API verification returned HTTP 401/403`: A replacement
  token was returned, but EasyStore did not authorize the read-only admin API;
  confirm this environment's store identity, pod ID and domain. No secret is
  persisted.
- `EasyStore token exchange connection failed`: Investigate network/TLS
  availability or upstream downtime instead of changing credentials.
- `EasyStore ... returned HTTP 429/5xx`: Wait for upstream recovery or review
  rate limits; the workflow does not retry blindly.

Rerun a forced **dry-run** in dev first, then prod. The job updates neither
environment's secret during a dry run.

## Token exchange request routing

EasyStore's published administrator JavaScript client includes
`easystore-pod-id`, `x-easystore-infra-pod-id`, and
`x-easystore-infra-default-domain` on requests after a store has been
selected. The rotation workflow must include the **selected GitHub
environment's** values on the token exchange itself, not only on the
subsequent read-only token verification request. Otherwise a valid
store-specific token may be rejected before the route reaches the proper
store context.

A 401 from the exchange still can mean the stored JWT is expired, revoked,
invalid for that store, or rejected for a different request-context reason.
If a forced dry run continues to return 401 after this change, check the
active store in EasyStore, that environment's `EASYSTORE_STORE_CODE`,
`EASYSTORE_STORE_DOMAIN` and `EASYSTORE_POD_ID`, and the dev environment
admin session JWT. Don't overwrite the production environment's credentials.

## EasyStore JWTs with no standard expiration field

The [October 10 dev forced dry run](https://github.com/kingyx3/cc-ez-theme/actions/runs/38019582083/job/114117377070) progressed beyond the EasyStore token exchange (no 401) but the **replacement** JWT did not carry a standard numeric `exp` claim. Earlier code rejected it before checking whether the replacement actually had store administration access. We cannot infer an expiration date from an absent JWT claim.

For this specific EasyStore format, the rotation now accepts a replacement with unknown expiry **only** if the previous JWT also lacked a numeric expiry, the replacement differs from the input, `sid` identifies the same store, and a read-only EasyStore admin API request with the replacement succeeds. The repository continues to reject expired/short-lived numeric-expiration JWTs and any attempt to downgrade a JWT with a known expiration into one without one.

For credentials with unknown expiry, the daily workflow performs a
read-only API health check, but only renews after 14 days since the saved
GitHub environment secret was updated (or earlier if that health check
returns HTTP 401/403). There is no promise of uninterrupted renewal from an
undocumented endpoint; monitor workflow failures and keep a recovery path
for a revoked or expired JWT. A successful **dry run** confirms authentication and admin verification but makes no GitHub/Cloudflare secret changes; the subsequent non-dry run is required to persist the returned token in the selected environment.

## 14-day renewal cadence and safety checks

The GitHub Actions workflow still runs every day, and each environment is
handled in a separate job. It performs a read-only EasyStore admin theme
listing using the stored credential on every run, including days on which
renewal will be skipped.

Instead of adding a timestamp variable that might drift from the saved
secret, the renewal script reads GitHub's metadata for that environment's
`EASYSTORE_ADMIN_TOKEN` using the REST endpoint
`GET /repos/{owner}/{repo}/environments/{environment}/secrets/EASYSTORE_ADMIN_TOKEN`.
GitHub returns `updated_at`, **not the secret value**. The existing
`EASYSTORE_ROTATION_GH_TOKEN` fine-grained PAT with **Environments:
read/write** permits this read. No new GitHub variables or secret
permissions are required.

- If the token is healthy and the environment secret was last saved fewer
  than 14 days ago, no renewal occurs.
- On or after day 14, the script performs a token exchange and read-only
  verification of the replacement, then writes only that environment's
  GitHub secret (and any explicitly configured Cloudflare Worker).
- Renewal happens earlier if the token is account-scoped, its numeric
  expiry is 14 days away or less, or EasyStore returns HTTP 401/403 on the
  daily health check. A revoked/expired credential may not be recoverable
  by exchange and will trigger an Actions failure requiring manual reseeding.
- A network error, rate limit or server error on the health check fails
  the workflow **without rotating**; it must not trigger unnecessary writes.
- `force=true` bypasses the scheduling interval; `dry_run=true` never
  writes secrets. A manual reseed resets the GitHub timestamp automatically.
- If reading secret metadata fails, the workflow fails closed rather than
  guessing whether renewal is due.

Scheduled workflow failures appear as failed GitHub Actions runs; configure
GitHub's Actions failure email notifications or other repository-level
alerting so that a missed renewal can be investigated promptly. The
reported GitHub timestamp is a **last-save** time, which can include manual
token replacements; it is not an EasyStore-issued expiry claim.
