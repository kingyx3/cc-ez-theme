# Admin API evidence

Public EasyStore admin frontend sources inspected on **2026-10-02**:

| Source | SHA-256 | Evidence |
| --- | --- | --- |
| [Main client](https://admin.easystore.co/assets/index-WRCYpubE.js) | `d65e0aaa80af0aca03c910f073e610c868432f17e6d1b04bf7a80a810310af87` | Methods, routes and request serialization |
| [Promotion editor](https://admin.easystore.co/assets/index-D8zrMJBf.js) | `878e547e0b169e79038489f4e61f30cf67cfe3f0b3c2137c5b050f8f988d6e79` | Flat promotion fields/defaults |
| [Product editor](https://admin.easystore.co/assets/index-C_eQG1LX.js) | `3c030d83978ea3439cca94a79d577a57336634da5677a2e2107a97a73cae0ad9` | Product/variant form fields |
| [Customer editor](https://admin.easystore.co/assets/index-DhhWi_BX.js) | `0f7500deaa88860c3a07437941951eacb5d1bb6c7b7d12d827eefd082f8b052c` | Customer form fields |

The [reference inventory](https://github.com/kingyx3/cc-ez-theme/blob/9eff3928833aecb2e265dff6176caa40ccf5e5b1/cloudflare/easystore-admin-mcp/src/admin-endpoints.json) contains 1,019 distinct normalized method/path pairs. It is research documentation, not an executable registry or a claim of exhaustive private-API coverage. Raw bundles and discovery scripts are not shipped.

Key client conventions:

- GET/DELETE send query parameters; POST/PUT/PATCH send JSON.
- POST `/admin/v2/store/vouchers` lists vouchers. Promotion creation uses POST `/admin/v2/store/discounts` with a flat body.
- Promotion update uses PUT `/admin/v2/store/discounts` with the ID in its body; deletion uses DELETE on the same path with ID in query.
- Bulk discount enable/disable uses JSON `discount_ids`; bulk delete uses query `discount_ids`. These are comma-separated strings.
- Product update uses PUT `/admin/v2/store/products/{product_id}` with matching body `id`.

Existing checkout/theme reads also have repository evidence in `scripts/easystore_admin_checkouts.py` and `docs/EASYSTORE_API_DEPLOYMENT.md`.

Frontend source confirms observed client behavior, not complete server-side schemas, account entitlements, authorization scopes, live compatibility or idempotency guarantees. Some GET routes have side effects and are excluded from read tools. Nested payload schemas are partial; server business validation can still reject requests. Lazy/computed/server-only routes can be absent. No live store mutations were performed for implementation or tests; the deployment workflow checks three reads without logging records.
