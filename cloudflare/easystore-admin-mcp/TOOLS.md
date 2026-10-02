# MCP tools

Connect an MCP client to the deployed Worker URL ending in `/mcp`, using `Authorization: Bearer <connector password>`. The deployment run summary contains the actual URL. Use the read or writer connector password configured in GitHub; the EasyStore admin token stays on the Worker.

## Available tools

| Tool | Arguments | What it does |
| --- | --- | --- |
| `easystore_admin_list_operations` | Optional `search` string | Returns available operation IDs, methods and descriptions. Search matches IDs/descriptions, ignoring case. |
| `easystore_admin_describe_operation` | Required `operation_id` | Returns the operation's route, argument schemas and defaults. Check this before making a call. |
| `easystore_admin_read` | Required `operation_id`; optional `path`, `query` objects | Executes a registered GET. Pass IDs in `path` and filters/pagination in `query`, as described by its schema. |
| `easystore_admin_write` | Required `operation_id`, `idempotency_key`; optional `path`, `query`, `body` objects | Executes a registered mutation. DELETE uses `query`; POST/PUT/PATCH use JSON `body`. |

The read password exposes the first three tools. The writer password also exposes the write tool when the deployment's **enable_writes** setting is on. Listing/describing operations respects the same access rules. Automatic deployments turn writes off; a manual deployment can enable them until the next deployment. Refresh the client's tools after changing this setting.

The registry currently contains 39 reads across products, customers, orders, collections, inventory, locations, promotions, vouchers, memberships, settings and themes. Its 11 mutations create/update products, customers and discounts; enable/disable discounts; and delete discounts/products. The available list and schemas come from `src/operations.js` and `src/schemas.js`.

## Example calls

These JSON objects are the parameters for MCP `tools/call`; the client handles the JSON-RPC envelope. The IDs and values below are examples.

Find customer operations:

```json
{"name":"easystore_admin_list_operations","arguments":{"search":"customer"}}
```

Inspect a customer read's accepted arguments:

```json
{"name":"easystore_admin_describe_operation","arguments":{"operation_id":"get_customer"}}
```

Read one customer:

```json
{"name":"easystore_admin_read","arguments":{"operation_id":"get_customer","path":{"customer_id":"123"}}}
```

Read one product page; increase `page` for subsequent pages:

```json
{"name":"easystore_admin_read","arguments":{"operation_id":"list_products","query":{"page":1,"limit":20}}}
```

With writer access enabled, inspect `update_customer` first, then update its note:

```json
{"name":"easystore_admin_write","arguments":{"operation_id":"update_customer","path":{"customer_id":"123"},"body":{"note":"Follow up next week"},"idempotency_key":"customer_note_intent_001"}}
```

Configure approval before mutations in Viktor. The Worker authenticates the writer but does not enforce human approval. The `idempotency_key` identifies one intended request: use 16–128 letters, digits, underscores or hyphens, and reuse it only for that same request. EasyStore's deduplication guarantees are unverified; the Worker never retries automatically. After a timeout, inspect the resource before retrying.

## Results and errors

Tools return JSON in MCP `content[0].text`. Reads/writes include `request_id`, `operation_id`, upstream HTTP `status`, and business `data`. Metadata tools return the operation list or definition. Reads fetch one page per call, with a maximum limit of 50 where supported.

A tool failure sets `isError: true` and returns an `error` code and `message`:

| Code | Meaning |
| --- | --- |
| `OPERATION_UNAVAILABLE` | Unknown, disabled or inaccessible operation |
| `INVALID_ARGUMENTS` | Missing/unsupported fields, invalid values or unsafe path IDs |
| `WRONG_TOOL` | GET requires the read tool; mutations require the write tool |
| `ADMIN_AUTH_REJECTED` | EasyStore rejected the admin token or its permissions |
| `UPSTREAM_UNCERTAIN` | Request failed/timed out; a mutation may have succeeded |
| `PAYLOAD_TOO_LARGE` | Use a smaller page or request |

An HTTP 401 from `/mcp` means the connector password is missing or invalid. For deployment, secret rotation and other limits, see [README.md](README.md).
