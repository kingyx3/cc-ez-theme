# MCP tools

Connect an MCP client to the deployed Worker URL ending in `/mcp`, using `Authorization: Bearer <connector password>`. The deployment run summary contains the actual URL. Use the read or writer connector password configured in GitHub; the EasyStore admin token stays on the Worker.

## Available tools

| Tool | Arguments | What it does |
| --- | --- | --- |
| `easystore_admin_list_operations` | Optional `search` string | Returns available operation IDs, methods and descriptions. Search matches IDs/descriptions, ignoring case. |
| `easystore_admin_describe_operation` | Required `operation_id` | Returns the operation's route, argument schemas and defaults. Check this before making a call. |
| `easystore_admin_read` | Required `operation_id`; optional `path`, `query` objects | Executes a registered GET. Pass IDs in `path` and filters/pagination in `query`, as described by its schema. |
| `easystore_admin_write` | Required `operation_id`, `idempotency_key`; optional `path`, `query`, `body` objects | Executes a registered mutation. DELETE uses `query`; POST/PUT/PATCH use JSON `body`. |

The read password exposes the first three tools. The writer password also exposes the write tool when the deployment's **enable_writes** setting is on. Listing/describing operations respects the same access rules. Automatic and manual deployments enable writes by default. A manual run with **enable_writes** unchecked temporarily disables them until the next deployment. Refresh the client's tools after changing this setting.

The registry currently contains 39 reads across products, customers, orders, collections, inventory, locations, promotions, vouchers, memberships, settings and themes. Its 12 mutations create unpublished products and update products, customers and discounts; reorder products; enable/disable discounts; and delete discounts/products. The available list and schemas come from `src/operations.js` and `src/schemas.js`.

## Access by role

☑ means the connector password can use it; ☐ means it cannot. Writer access to mutations also requires the deployment's **enable_writes** setting, which is on by default. Mutations go through `easystore_admin_write`; reads go through `easystore_admin_read`.

### Tools

| Tool | Reader | Writer |
| --- | :---: | :---: |
| `easystore_admin_list_operations` | ☑ | ☑ |
| `easystore_admin_describe_operation` | ☑ | ☑ |
| `easystore_admin_read` | ☑ | ☑ |
| `easystore_admin_write` | ☐ | ☑ |

### Operations

| Operation | Method | Reader | Writer | Limits |
| --- | --- | :---: | :---: | --- |
| `list_abandoned_checkouts` | GET | ☑ | ☑ |  |
| `list_themes` | GET | ☑ | ☑ |  |
| `list_products` | GET | ☑ | ☑ |  |
| `get_product` | GET | ☑ | ☑ |  |
| `list_customers` | GET | ☑ | ☑ |  |
| `get_customer` | GET | ☑ | ☑ |  |
| `list_orders` | GET | ☑ | ☑ |  |
| `get_order` | GET | ☑ | ☑ |  |
| `list_collections` | GET | ☑ | ☑ |  |
| `get_collection` | GET | ☑ | ☑ |  |
| `list_locations` | GET | ☑ | ☑ |  |
| `get_location` | GET | ☑ | ☑ |  |
| `list_stock_adjustments` | GET | ☑ | ☑ |  |
| `get_stock_adjustment` | GET | ☑ | ☑ |  |
| `list_purchase_orders` | GET | ☑ | ☑ |  |
| `get_purchase_order` | GET | ☑ | ☑ |  |
| `list_inventory_transfers` | GET | ☑ | ☑ |  |
| `get_inventory_transfer` | GET | ☑ | ☑ |  |
| `list_discounts` | GET | ☑ | ☑ |  |
| `get_discount` | GET | ☑ | ☑ |  |
| `list_discounts_new` | GET | ☑ | ☑ |  |
| `list_vouchers` | GET | ☑ | ☑ |  |
| `list_voucher_campaigns` | GET | ☑ | ☑ |  |
| `list_inventory_levels` | GET | ☑ | ☑ |  |
| `get_inventory_level` | GET | ☑ | ☑ |  |
| `get_general_settings` | GET | ☑ | ☑ |  |
| `list_enabled_channels` | GET | ☑ | ☑ |  |
| `list_store_users` | GET | ☑ | ☑ |  |
| `get_store_global` | GET | ☑ | ☑ |  |
| `list_discount_usages` | GET | ☑ | ☑ |  |
| `list_discount_setting_logs` | GET | ☑ | ☑ |  |
| `get_discount_visual_settings` | GET | ☑ | ☑ |  |
| `list_discount_redemption_logs` | GET | ☑ | ☑ |  |
| `list_customer_vouchers` | GET | ☑ | ☑ |  |
| `list_customer_addresses` | GET | ☑ | ☑ |  |
| `get_customer_membership` | GET | ☑ | ☑ |  |
| `list_order_fulfillments` | GET | ☑ | ☑ |  |
| `get_product_variants` | GET | ☑ | ☑ |  |
| `list_stock_adjustment_items` | GET | ☑ | ☑ |  |
| `create_discount` | POST | ☐ | ☑ |  |
| `update_discount` | PUT | ☐ | ☑ |  |
| `enable_discounts` | PUT | ☐ | ☑ |  |
| `disable_discounts` | PUT | ☐ | ☑ |  |
| `delete_discount` | DELETE | ☐ | ☑ |  |
| `delete_discounts` | DELETE | ☐ | ☑ |  |
| `delete_products` | DELETE | ☐ | ☑ |  |
| `create_customer` | POST | ☐ | ☑ |  |
| `update_customer` | PUT | ☐ | ☑ |  |
| `create_product` | POST | ☐ | ☑ | Unpublished only (`is_published: 0`) |
| `update_product` | PUT | ☐ | ☑ | Can unpublish; cannot publish |
| `update_product_positions` | PATCH | ☐ | ☑ |  |

### Not available to either role

| Action | Reader | Writer |
| --- | :---: | :---: |
| Publish a product (new or existing) | ☐ | ☐ |
| Publish or change themes | ☐ | ☐ |
| Any route not listed above | ☐ | ☐ |

Publish products in EasyStore Admin. This table must list every enabled operation in `src/operations.js`; the tests fail if it falls out of date.

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

To change product display positioning, first read the complete product order from `list_products` using the same position sort used in EasyStore Admin. Build the complete desired top-to-bottom product ID list, then call:

```json
{"name":"easystore_admin_write","arguments":{"operation_id":"update_product_positions","body":{"product_ids":[17473183,17067738,17447825]},"idempotency_key":"product_position_intent_001"}}
```

Products can be unpublished but not published. `create_product` only accepts `is_published: 0`. `update_product` accepts `is_published: 0` to unpublish; any other value is checked against a fresh read of the product and rejected with `PUBLISH_NOT_PERMITTED` unless the product is already in that state. Publish products in EasyStore Admin.

`update_product_positions` sends `PATCH /admin/v2/store/products/positions`. Its `product_ids` array is the full display order, not a partial move instruction or a single product `position` value. Preserve every product ID exactly once and change only the relative ordering you intend.

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
| `PUBLISH_NOT_PERMITTED` | The request would publish a product; the worker can only create unpublished products and unpublish existing ones |

An HTTP 401 from `/mcp` means the connector password is missing or invalid. For deployment, secret rotation and other limits, see [README.md](README.md).
