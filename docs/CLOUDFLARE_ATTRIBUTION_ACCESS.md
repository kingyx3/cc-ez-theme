# Public Cloudflare Access policy for `cc-attribution`

`go.cardboard.sg` is a public marketing redirect and storefront touch endpoint.
It must never require a Cloudflare Access login before the Worker runs.

Cloudflare can protect all Workers on an account by default. In that setup, a
specific public Worker needs its own Worker-level Access application with a
`bypass` policy that includes `Everyone`.

The repository manages that exception during Worker deployment.

## Deployment behavior

The Worker workflow runs in this order:

```text
validate/tests
→ apply D1 migrations
→ rerun D1 migrations to prove idempotence
→ deploy cc-attribution
→ ensure Worker-level Access bypass for Everyone
→ verify https://go.cardboard.sg/health publicly reaches cc-attribution
```

If the Access API step fails, or the public health URL still redirects to an
Access login, the deployment fails instead of reporting success.

The Access step is idempotent:

- if no Worker-specific Access application exists, it creates one with a bypass
  policy;
- if the application exists without a public bypass, it adds the bypass policy;
- if a bypass-for-Everyone policy already exists, it makes no change.

The implementation is
`cloudflare/attribution-worker/scripts/ensure-public-access.js` and is covered by
Worker unit tests.

## Required Cloudflare API permission

The token used for the Access step needs:

```text
Access: Apps and Policies Write
```

Preferred setup:

```text
GitHub repository secret: CLOUDFLARE_ACCESS_API_TOKEN
```

Use a Cloudflare API token scoped to the Cardboard Cloudflare account with only
that Access permission where possible.

For backwards compatibility, the workflow falls back to the existing
`CLOUDFLARE_API_TOKEN` if `CLOUDFLARE_ACCESS_API_TOKEN` is not configured. That
fallback only works when the existing token also has `Access: Apps and Policies
Write` in addition to its Worker/D1 permissions.

`CLOUDFLARE_ACCOUNT_ID` is shared with the existing Worker deployment.

## Expected public health response

After deployment this URL must be reachable without cookies, identity or OTP:

```text
https://go.cardboard.sg/health
```

Expected JSON:

```json
{"ok":true,"worker":"cc-attribution"}
```

A `302` to a `cloudflareaccess.com` login page is a deployment failure.

## Why this is Worker-level

The exception is attached to the Worker rather than one hostname so account-wide
Worker protection cannot silently break another route or Custom Domain attached
to `cc-attribution` later. `go.cardboard.sg` remains the production Custom Domain;
EasyStore apex/www DNS is unrelated and should not be changed for this policy.
