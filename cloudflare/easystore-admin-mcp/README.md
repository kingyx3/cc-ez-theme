# EasyStore admin MCP

General CCPL admin access for Viktor: **39 reads and 12 mutations** covering products, customers, orders, inventory, settings and promotions. The Worker runs on Cloudflare; setup and deployment run entirely in GitHub Actions.

## Deploy from GitHub

The deployment job uses the existing GitHub **`prod` environment** for `main`. It can read `prod` environment secrets and repository Actions secrets. Keep the existing `EASYSTORE_ADMIN_TOKEN` in `prod`; the Cloudflare and connector secrets can remain at repository level or be configured in `prod`.

| Secret | Value |
| --- | --- |
| `CLOUDFLARE_API_TOKEN` | Token with Workers Scripts edit permission for the intended account |
| `CLOUDFLARE_ACCOUNT_ID` | Intended account ID |
| `EASYSTORE_ADMIN_TOKEN` | Existing EasyStore admin token, without `Bearer ` |
| `EASYSTORE_ADMIN_MCP_READ_TOKEN` | New random password, at least 32 characters |
| `EASYSTORE_ADMIN_MCP_WRITE_TOKEN` | Different random password, at least 32 characters |

Reuse existing Cloudflare/admin secrets where available. Generate the connector passwords in your password manager. Merging changes to the Worker or its workflow into `main` automatically verifies and deploys them. For secret updates without code changes, use **Actions → EasyStore admin MCP → Run workflow** on `main`. The workflow verifies code, deploys code and secrets together, checks authenticated MCP plus one product/customer/discount read, and returns the actual `/mcp` URL in the run summary. No commands need to run on your computer.

PRs run checks only. Relevant pushes to `main` deploy after checks pass; manual runs from `main` remain available. Writes are enabled by default on automatic and manual deployments. A manual run with **enable_writes** unchecked disables them until the next deployment. A failed hosted check does not undo an already completed deployment.

## Connect Viktor

See [TOOLS.md](TOOLS.md) for the available tools, arguments, example calls and errors.

Use **Integrations → Add Custom → MCP Server**, enter the URL, and supply the writer connector password for management or the read connector password for read-only access ([Viktor instructions](https://viktor.com/docs/custom-integrations)). Requests use `Authorization: Bearer <connector password>`.

| Tool | Purpose |
| --- | --- |
| `easystore_admin_list_operations` | Find enabled operations available to this credential |
| `easystore_admin_describe_operation` | Inspect method/path, argument schemas and defaults |
| `easystore_admin_read` | Execute a registered GET/page |
| `easystore_admin_write` | Execute a registered mutation; requires the writer password and **enable_writes** |

Example: `{"operation_id":"list_products","query":{"page":1,"limit":20}}`.

To manage promotions, product positioning and other mutations, use the writer password in Viktor. The writer can create unpublished products and unpublish existing ones but cannot publish products; a request that would publish is rejected with `PUBLISH_NOT_PERMITTED`. Product positioning is exposed as `update_product_positions`, which sends the observed admin `PATCH /admin/v2/store/products/positions` request with the complete desired product ID order. The read password always provides read-only access. Configure approval before mutations in Viktor; the Worker does not enforce human approval. Every mutation requires a stable `idempotency_key` of 16–128 letters/digits/underscores/hyphens. Requests are never automatically retried, and EasyStore's deduplication guarantees are unverified. Inspect the resource after a timeout before retrying.

## Update APIs with an AI harness

Edit `src/operations.js` for explicit methods, routes and operation IDs; edit `src/schemas.js` for shared argument schemas. Preserve closed top-level schemas, correct side-effect classification and store routing. Submit a PR; GitHub Actions checks and tests it, then automatically deploys the changes after merge. There is no discovery workflow, recorder, importer or runtime catalog tool.

The [reference inventory of 1,019 observed method/path pairs](https://github.com/kingyx3/cc-ez-theme/blob/9eff3928833aecb2e265dff6176caa40ccf5e5b1/cloudflare/easystore-admin-mcp/src/admin-endpoints.json) remains available as a fixed research snapshot. It is not bundled into the Worker. Source evidence and limitations are in [ADMIN_API_EVIDENCE.md](ADMIN_API_EVIDENCE.md). Only the 51 explicit operations are callable; frontend-derived nested schemas are partial and do not prove complete server validation or live compatibility. Multipart/binary APIs need dedicated adapters.

## Operational controls

The upstream is fixed to `https://api.easystore.co`, store `cardboardcollective.easy.co`, pod `1007`. Bearer auth is the default; change `EASYSTORE_ADMIN_AUTH_MODE` in `wrangler.jsonc` to `access-token` only if the credential requires it. `ADMIN_AUTH_REJECTED` indicates expired/revoked credentials or insufficient permissions. Replace secrets in GitHub and rerun deployment to rotate credentials. Temporarily disable writes by rerunning with **enable_writes** off; the next automatic deployment restores the enabled default. Revert the relevant code on `main` to trigger an automatic rollback deployment.

GET/DELETE use query parameters; POST/PUT/PATCH use JSON. Callers cannot supply methods, URLs, headers or store routing. Unknown operations, extra top-level fields and unsafe paths are rejected. Reads are capped at 50 records where a limit is defined; responses at 2 MiB; mutation bodies at 256 KiB; incoming MCP requests at 320 KiB. Upstream requests time out after 20 seconds and redirects are blocked.

Successful reads return business data to the authorized client, with known credentials redacted. Errors and audit logs omit upstream bodies, records and credentials. Shared keys identify roles, not people. Browser origins other than the Worker's own origin are rejected. `/health` is public and non-sensitive. This implementation supports static-key authentication with MCP SDK v2 and legacy clients; OAuth is not implemented.
