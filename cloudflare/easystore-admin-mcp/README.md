# EasyStore admin MCP Worker

General EasyStore admin access for Viktor, backed by a reviewed operation registry. This is independent of the public `/api/3.0` API and of the Slack webhook Worker.

The Worker uses Cloudflare's `createMcpHandler` with the MCP SDK v2 and stateless legacy-client compatibility. An actual SDK v1 client is exercised against the bundled Worker in Miniflare. It supports JSON admin operations across resources; it is not voucher-specific. Multipart uploads, binary responses, GraphQL, and operations outside `/admin/v2/store/` need explicit typed adapters.

## Current operations

| Operation | State | Evidence |
| --- | --- | --- |
| `list_abandoned_checkouts` | Enabled GET; 50 records max per page | `scripts/easystore_admin_checkouts.py` |
| `list_themes` | Enabled GET | `docs/EASYSTORE_API_DEPLOYMENT.md` |
| `publish_theme` | Disabled write | Existing theme deployment workflow |
| `update_email_template` | Disabled write | `.github/workflows/easystore-email-templates.yml` |

These are routes already used by this repository, not newly live-tested here. Voucher/promotion routes have not been discovered yet. Theme ZIP import is multipart and deliberately has no generic JSON adapter.

## Install and verify

```bash
cd cloudflare/easystore-admin-mcp
npm ci
npm run check
npm test
```

`npm test` first bundles the Worker with a deployment dry run, then runs API/discovery and real MCP transport tests. No test calls live EasyStore or deploys a Worker. Node 22+ is required.

For local development, copy `.dev.vars.example` to `.dev.vars`, enter secrets locally, and run `npm run dev`. Never commit `.dev.vars`.

## Deploy

Authenticate Wrangler to the intended Cloudflare account using `npx wrangler login`, or set a scoped `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` in your own deployment environment. No Cloudflare credentials are included in this package.

```bash
npx wrangler secret put EASYSTORE_ADMIN_TOKEN
npx wrangler secret put MCP_READ_TOKEN
npx wrangler secret put MCP_WRITE_TOKEN
npm run deploy
```

Each `secret put` prompts locally. `EASYSTORE_ADMIN_TOKEN` must be the existing **admin** token, without `Bearer `. The connector keys must be distinct random secrets of at least 32 characters (for example, 32 random bytes encoded as hex). Generate/store them in your password manager and paste them only into the secret prompts and Viktor's credential field.

Confirm the pod/domain against a current admin request before deployment. Defaults use this repo's observed `1007` and `cardboardcollective.easy.co`. Upstream origin is fixed to `https://api.easystore.co` and store domain is pinned to Cardboard Collective. `EASYSTORE_ADMIN_AUTH_MODE` is `bearer` by default; choose `access-token` only if your current credential needs `EasyStore-Access-Token`. The repo checkout reader has used both header shapes. No auth fallback or token exchange happens on a write.

Wrangler prints the real deployed URL. Append `/mcp`; the service also provides a non-sensitive `GET /health`. Do not invent the workers.dev account subdomain.

## Connect Viktor

Viktor documents **Integrations → Add custom MCP** and detection of static-key authentication:
https://viktor.com/blog/how-to-connect-tools-your-ai-employee-doesnt-support-yet

Paste the deployed `/mcp` URL and supply `MCP_READ_TOKEN` in Viktor's secure credential UI. Requests must use `Authorization: Bearer <connector key>`. Never give Viktor `EASYSTORE_ADMIN_TOKEN`.

Tools:

- `easystore_admin_list_operations(search?)`: find enabled operations.
- `easystore_admin_describe_operation(operation_id)`: inspect exact argument schemas.
- `easystore_admin_read(operation_id, path?, query?)`: call an enabled GET.
- `easystore_admin_write(operation_id, path?, query?, body?, idempotency_key)`: appears only for the writer key with `ENABLE_WRITES=true`.

Example read arguments:

```json
{"operation_id":"list_abandoned_checkouts","query":{"page":1,"limit":20}}
```

To enable writes, review/enable particular operations in `src/operations.json`, set `ENABLE_WRITES` to `true` in `wrangler.jsonc`, redeploy, and connect Viktor with `MCP_WRITE_TOKEN`. Both permissions are required. Keep approval-before-write configured in Viktor. MCP annotations describe side effects; they do not enforce human approval. Anyone holding the writer key can call enabled writes when the toggle is on.

## Discover many endpoints with one session

A bearer token grants authentication; it does not enumerate endpoints or provide schemas. Use these routes in order:

1. **Internal OpenAPI JSON from EasyStore:** ask EasyStore for their admin-v2 spec or an internal collection they permit you to use. A complete spec is the best route to complete coverage.
2. **Local authenticated recorder:** sign in once and browse admin sections/forms normally. It gathers requests across tabs, normalizes numeric/UUID resource IDs, infers JSON body shapes, and collects literal route hints from loaded EasyStore-hosted JS bundles. It never clicks, saves, creates or deletes anything for you.
3. **Existing HAR:** record a normal admin session with DevTools Network → Preserve log. Import the HAR locally; share only the generated shape catalog.

### Local recorder (recommended practical next step)

Run on your own computer with a desktop/browser available:

```bash
cd cloudflare/easystore-admin-mcp
npm ci
npx playwright install chromium
npm run capture
```

Sign in in the opened browser, select the Cardboard Collective store, and browse Products, Orders, Customers, Discounts/Vouchers, Themes, Settings and other sections you want supported. Opening lists/detail screens/edit forms captures reads and loads lazy JS bundles. It does not capture an unseen write payload until that action actually occurs during your normal work. Use a test store if you want to exercise create/update flows for discovery.

Press Enter in the terminal to finish. Output:

- `captures/operations.pending.json`: observed methods/routes and argument shapes, all disabled.
- `captures/operations.pending.bundle-routes.json`: static route hints without methods/payloads.

Authentication lives in an ephemeral browser profile; no saved login state, cookies, bearer headers, request example values, or customer response data are exported. Literal route identifiers and property names can still contain private/custom names. Inspect the generated files before sharing. Captures are gitignored and created with owner-only permissions where supported.

Share those two generated JSON files with the implementer, instead of individual cURL commands or raw HAR files. One session can cover many resources.

### HAR and OpenAPI importers

```bash
npm run import:har -- /local/path/admin.har
npm run import:openapi -- /local/path/internal-openapi.json
```

The raw HAR stays local: it may contain credentials and customer data even when its headers are sanitized. The importer copies only route/schema information. Both importers default to `captures/operations.pending.json`; use an explicit second output path to keep multiple captures.

The OpenAPI importer supports JSON OpenAPI 3.x, non-cyclic local `$ref`s, path/query parameters, and JSON object bodies. Paths may be absolute admin routes or relative to an `https://api.easystore.co/admin/v2/store` server. External refs, circular schemas, multipart, header parameters, unusual parameter serialization and non-object bodies need review/adapters. Unsupported bodies are recorded in `reviewNotes` and never enabled.

No client-side method can guarantee **all** private admin endpoints: traffic captures cover exercised actions; JS may omit lazy chunks, construct paths dynamically or lack server-only operations. A full internal spec or authorized frontend/source access is needed for broader coverage. Knowing a route alone does not prove its payload or effects.

## Promote the catalog

This is intentionally a code-reviewed registry, not a runtime endpoint that allows the AI to add arbitrary permissions.

1. Deduplicate candidates against existing routes; rename operation IDs to clear stable business names.
2. Verify method/path and semantics, including whether a GET has side effects. A side-effecting GET must not be admitted as a read operation.
3. Normalize any remaining resource IDs/slugs into required path parameters. The Worker accepts only alphanumeric, underscore and hyphen path values, up to 128 characters.
4. Verify required fields, enum/range constraints, maximum discount amounts and other business limits against a test store/spec. Observed traffic does not establish complete schemas; optional observed keys are not automatically required.
5. Add approved entries to `src/operations.json`; set `enabled:true` only after review. Top-level path/query/body schemas must be closed objects. Only JSON object bodies and scalar query values are supported.
6. `npm run check && npm test`, then redeploy. Reconnect/refresh Viktor to load tools if write availability changes.

The generic transport does not impose voucher-specific amount/customer/product constraints; put those in the corresponding operation schema or a typed adapter before enabling it.

## Failure behavior and operations

- Unknown/disabled operations, extra query/body keys, unsafe path parameters and wrong read/write tools are rejected before upstream access.
- Caller cannot supply methods, upstream URLs, headers, store routing or credentials.
- Upstream redirects are blocked. Requests time out after 20 seconds; response JSON is capped at 2 MiB; request body at 256 KiB. Large reads should be paginated.
- No automatic retry. Every write requires a stable caller-generated idempotency key and sends the repo's observed `phase1-dummy:web:` header. EasyStore's deduplication guarantees for private endpoints are unverified. On a timeout, inspect the resulting resource before retrying. This does not provide exactly-once execution.
- `401`/`403` from EasyStore become `ADMIN_AUTH_REJECTED` (expired/revoked token or insufficient rights). Replace the admin secret using Wrangler; the connector keys are independent.
- Upstream error bodies are not echoed. Known credential values and credential-like fields are redacted from successful responses. Legitimate business data from reads is returned to Viktor, so use the appropriate workspace access settings.
- Audit logs contain request ID, operation ID, read/write credential role, method, HTTP status and outcome, without request payloads, query values or tokens. Shared keys identify a role, not an individual person.
- Browser origins other than the Worker's own origin are rejected. Server-to-server Viktor calls normally send no Origin. OAuth is not implemented; this build targets Viktor's documented static-key option.

Cloudflare implementation reference:
https://developers.cloudflare.com/agents/model-context-protocol/apis/handler-api/
