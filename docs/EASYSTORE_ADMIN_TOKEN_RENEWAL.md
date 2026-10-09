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
5. Automatic daily checks subsequently rotate each environment's
   token when it has **14 days or less** remaining; otherwise they leave
   the secrets unchanged.

The script verifies that the returned JWT is different, has the same
store identity (sid), extends expiration sufficiently, and works against
the admin theme-list API before updating secrets. The public EasyStore
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
The renewal script now attempts one authenticated store-token exchange for
such credentials, regardless of the 14-day threshold. It **does not** assume
an indefinite lifetime: the replacement must be a different, store-scoped JWT
with a valid numeric `exp` at least 20 days in the future, and it must pass
a read-only EasyStore admin API check before any secret updates are allowed.

A missing or malformed input `exp` causes a forced authenticated exchange;
only output JWTs with valid numeric `exp` values are accepted. An
invalid/expired upstream credential will fail at the EasyStore exchange.
The workflow never prints JWT payloads. On continued failures, replace only
the failing environment's `EASYSTORE_ADMIN_TOKEN` with its own valid EasyStore
admin session JWT, then perform a forced dry run before enabling live writes.
