# EasyStore admin MCP on Cloudflare

A general EasyStore admin MCP for Cardboard Collective and Viktor. Setup, verification and deployment run in GitHub Actions; nothing needs to run on your computer. This Worker is independent of the public `/api/3.0` API and the Slack webhook Worker.

## Coverage

The static `src/admin-endpoints.json` catalog contains **1,019 distinct method/path pairs** found in EasyStore's publicly served admin frontend on 2026-10-02. Discovery was performed while implementing this change; no browser recorder, HAR importer or discovery service is shipped. Evidence and limits are recorded in [ADMIN_API_EVIDENCE.md](ADMIN_API_EVIDENCE.md).

`src/operations.json` defines 52 operations: **39 reads and 11 callable mutations**, plus two disabled legacy mutations. Read coverage includes products, customers, orders, collections, locations, inventory, purchase orders, promotions, vouchers, memberships, themes and settings. Mutations cover creating/updating products, customers and discounts; enabling/disabling discounts; and deleting discounts or products. Writes default to **off**.

The catalog is broader than the executable registry. Finding a route establishes its method/path, not every required server field or its safety. A GET can have side effects. Catalog-only routes do not grant permission to invoke arbitrary endpoints. Multipart uploads, binary responses, GraphQL and routes outside `/admin/v2/store/` require dedicated adapters. Public frontend discovery cannot establish all private/server-only endpoints; EasyStore's internal admin OpenAPI specification would provide the strongest additional coverage. No individual endpoint copies or local recordings are needed from the user.

The current schemas use frontend field names and editor defaults with closed top-level objects. Some nested payloads are only partially constrained; these are not a complete server specification. The routes have not been live-tested against the store during implementation. The deployment workflow checks three authenticated live reads and never performs a mutation.

## GitHub-only setup

1. Review and merge the PR. The manual workflow button becomes available once the workflow exists on `main`. This workflow validates PRs and main pushes but deploys only on an explicit manual run from `main`.
2. Open the repository's **Settings → Secrets and variables → Actions**. Reuse or add these repository secrets:

   | GitHub secret | Value |
   | --- | --- |
   | `CLOUDFLARE_API_TOKEN` | Token scoped to the intended account, with Workers Scripts edit permission |
   | `CLOUDFLARE_ACCOUNT_ID` | Intended Cloudflare account ID |
   | `EASYSTORE_ADMIN_TOKEN` | Existing EasyStore admin token, without the `Bearer ` prefix |
   | `EASYSTORE_ADMIN_MCP_READ_TOKEN` | A new random connector key of at least 32 characters |
   | `EASYSTORE_ADMIN_MCP_WRITE_TOKEN` | A different random connector key of at least 32 characters |

   Generate both connector keys in your password manager's generator. Paste credentials only into GitHub's secret fields and Viktor's credential field. The Worker uses its own connector keys; the EasyStore token stays in Cloudflare.
3. Open **Actions → EasyStore admin MCP → Run workflow**, select `main`, keep **deploy** and **live_read_checks** selected, and leave **enable_writes** off for the first deployment.
4. The workflow installs pinned dependencies, checks the catalog/registry, bundles and tests the real MCP transport, atomically deploys code with Cloudflare secrets, and checks hosted authenticated tool discovery. With live checks selected, it also requests one product, customer and discount page with limit 1. Only pass/fail status is logged, never returned records.
5. Open the completed run's summary and copy its actual **MCP URL**. It uses the workers.dev URL returned by Cloudflare with `/mcp` appended. No account subdomain needs to be guessed.

The existing store configuration is `cardboardcollective.easy.co`, pod `1007`, and bearer authentication, based on repository admin integrations. If the live checks return `ADMIN_AUTH_REJECTED`, replace the admin secret or verify its permissions. If this store requires the `EasyStore-Access-Token` header instead, change `EASYSTORE_ADMIN_AUTH_MODE` in `wrangler.jsonc` to `access-token` through a reviewed GitHub edit and rerun the workflow. No automatic authentication fallback occurs during a mutation.

A failed hosted/live check does not undo an already completed Cloudflare deployment. Review the run's status before connecting. Wrangler or secret output is never printed by the deploy script.

## Connect Viktor

Use **Integrations → Add custom MCP**, enter the deployed MCP URL, and supply the read connector key in Viktor's secure static-key credential field. Requests use `Authorization: Bearer <connector key>`. See [Viktor's custom MCP instructions](https://viktor.com/blog/how-to-connect-tools-your-ai-employee-doesnt-support-yet).

| Tool | Purpose |
| --- | --- |
| `easystore_admin_search_endpoints` | Search the static catalog by resource, frontend operation name or method; results identify executable registry matches |
| `easystore_admin_list_operations` | Find operations available to this credential |
| `easystore_admin_describe_operation` | Get method/path, argument schemas and defaults before a call |
| `easystore_admin_read` | Execute one registered GET/page |
| `easystore_admin_write` | Execute a registered mutation; available only with the writer key and the deployment write toggle enabled |

Example read arguments:

```json
{"operation_id":"list_products","query":{"page":1,"limit":20}}
```

To enable mutations, rerun **EasyStore admin MCP** on `main` with **enable_writes** selected and connect Viktor using the writer key. Configure approval before mutations in Viktor. The MCP annotations and instruction text do not enforce approval; possession of the writer key authorizes registered writes while the toggle is on. Reader keys continue to expose only reads.

Every mutation requires a caller-generated `idempotency_key` of 16–128 alphanumeric/underscore/hyphen characters. The Worker forwards the repository's observed `phase1-dummy:web:` header. EasyStore's deduplication guarantees are unverified, so inspect the resource after a timeout before retrying. Requests are never retried automatically.

## Maintenance and controls

All future changes can be made in GitHub and verified by the same workflow. To expand executable coverage, verify the catalog entry's fields/semantics from admin frontend source or an internal specification, add its explicit schema to `src/operations.json`, then submit a PR. CI validates the registry and transport. Merely adding a catalog route never makes it executable.

To disable writes, rerun the deployment workflow with **enable_writes** off and refresh Viktor's tools. Rotate a connector key in GitHub secrets and redeploy to revoke it. Replace the EasyStore admin secret and redeploy to renew upstream access. To roll back code, revert the change on `main`, then run the deployment workflow again; verification or a main push alone does not deploy.

The upstream origin is fixed to `https://api.easystore.co`, with store routing pinned to Cardboard Collective. Callers cannot supply their own URLs, methods, headers, credentials or routing. Unknown/disabled operations, unexpected top-level fields, unsafe path parameters and mismatched read/write calls are rejected before upstream access. GET and DELETE send query parameters; POST/PUT/PATCH send JSON bodies. Product update body/path IDs must agree; percentage discounts cannot exceed 100.

Reads support up to 50 records per page where a limit is defined. Upstream JSON responses are capped at 2 MiB, mutation bodies at 256 KiB, and the incoming MCP request at 320 KiB. Upstream requests time out after 20 seconds and redirects are blocked. Error responses never echo upstream bodies. Successful reads return business data to the authorized MCP client, with known credentials and credential-like fields redacted.

Audit records contain request ID, credential role, operation, method, HTTP status and outcome, without payloads, query values or tokens. A shared credential identifies a role rather than a person. Server-to-server clients should omit `Origin`; browser origins other than the Worker's own origin are rejected. `/health` is a public non-sensitive health check. OAuth is not implemented; this build uses Viktor's static-key connection option.

The implementation uses Cloudflare's [MCP handler API](https://developers.cloudflare.com/agents/model-context-protocol/apis/handler-api/), MCP SDK v2 and stateless legacy compatibility. CI exercises a real SDK v1 client against the bundled Worker, including initialization, tool discovery, schema descriptions, permission separation and unavailable operations. Hosted checks accept JSON and legacy SSE responses.
