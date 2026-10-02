# Admin API evidence

Discovery date: **2026-10-02**. Sources were fetched directly from the public EasyStore admin site while implementing this Worker. Raw frontend bundles and discovery scripts are not included in the repository. The checked-in catalog records method/path facts and frontend operation names, not copied frontend implementations or user data.

| Public source | SHA-256 | Evidence used |
| --- | --- | --- |
| [Admin main bundle](https://admin.easystore.co/assets/index-WRCYpubE.js) | `d65e0aaa80af0aca03c910f073e610c868432f17e6d1b04bf7a80a810310af87` | API client methods, request serialization and route call sites |
| [Promotion editor](https://admin.easystore.co/assets/index-D8zrMJBf.js) | `878e547e0b169e79038489f4e61f30cf67cfe3f0b3c2137c5b050f8f988d6e79` | Flat promotion payload field names, editor defaults and create/update calls |
| [Product editor](https://admin.easystore.co/assets/index-C_eQG1LX.js) | `3c030d83978ea3439cca94a79d577a57336634da5677a2e2107a97a73cae0ad9` | Product and variant form fields |
| [Customer editor](https://admin.easystore.co/assets/index-DhhWi_BX.js) | `0f7500deaa88860c3a07437941951eacb5d1bb6c7b7d12d827eefd082f8b052c` | Customer form fields and flat create payload |

The main bundle contained 1,047 recognizable GET/POST/PUT/PATCH/DELETE route call sites. Deduplicating normalized method/path pairs yielded 1,018 catalog entries. A manually verified product update path derived from `product.id` adds one, for **1,019** total. Dynamic path segments are named `{id_1}`, `{id_2}`, etc. in the catalog; executable operations use meaningful parameter names. A catalog match compares method and path structure, not those placeholder names.

## Confirmed request distinctions

| Frontend operation | Method/path | Client behavior |
| --- | --- | --- |
| `listVouchers` | POST `/admin/v2/store/vouchers` | Lists/filter vouchers with JSON; this is not voucher creation |
| `createDiscount` | POST `/admin/v2/store/discounts` | Sends the editor's flat params object |
| `updateDiscount` | PUT `/admin/v2/store/discounts` | Sends a flat body including discount ID, rather than an ID in the path |
| `deleteDiscount` | DELETE `/admin/v2/store/discounts` | ID is a query parameter |
| Bulk discount enable/disable | PUT `/admin/v2/store/discounts/bulk_enable` or `/bulk_disable` | JSON `discount_ids` value is a comma-separated string |
| Bulk discount delete | DELETE `/admin/v2/store/discounts/bulk_delete` | `discount_ids` is in query parameters |
| Product update | PUT `/admin/v2/store/products/{product_id}` | Path is taken from the submitted product body's `id` |
| New discount list | GET `/admin/v2/store/discounts/list` | Query parameters |
| New voucher list | GET `/admin/v2/store/vouchers/list` | Query parameters |

The shared admin client sends GET and DELETE arguments through Axios `params`, and POST/PUT/PATCH through JSON `data`. This is why DELETE operations have query schemas and no request body.

The pre-existing checkout/theme routes, disabled theme publish and disabled email template update also have repository evidence in `scripts/easystore_admin_checkouts.py`, `docs/EASYSTORE_API_DEPLOYMENT.md` and the corresponding deployment workflows. These are retained with their existing evidence references.

## What remains unverified

Frontend call sites establish observed methods, path templates and client conventions. They do not establish every server-side required field, authorization scope, account feature entitlement, idempotency behavior or current successful response. Lazy chunks, computed routes, server-only routes and routes outside the catalog's store-admin scope can be missing. Some GET actions modify integration state, so the full catalog is not automatically enabled as read-only tools.

The 50 callable operations are an explicit implementation subset. Editor-derived JSON schemas constrain top-level fields and selected nested fields; some nested arrays/objects remain partially specified. A code-valid request can still be rejected by EasyStore's business validation. Production read success is checked during the authorized GitHub deployment; mutation behavior requires a separately approved real action or test store. No live store mutations were performed for discovery or tests.

For exhaustive server coverage, EasyStore's internal admin-v2 OpenAPI document, supported SDK or authorized server route specification would be preferable. It is not necessary for the user to collect each endpoint individually.
