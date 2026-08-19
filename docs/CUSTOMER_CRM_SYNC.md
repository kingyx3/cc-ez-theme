# EasyStore customer CRM sync

`.github/workflows/sync-easystore-customers-hubspot.yml` independently syncs EasyStore customers into HubSpot at **00:00, 06:00, 12:00 and 18:00 Singapore time** and can also be run manually with `workflow_dispatch`.

## Required repository secrets

- `EASYSTORE_ACCESS_TOKEN` — an EasyStore Public API access token with the `read_customers` scope.
- `HUBSPOT_ACCESS_TOKEN` — a HubSpot access token with `crm.objects.contacts.read` and `crm.objects.contacts.write`.

The existing `EASYSTORE_ADMIN_TOKEN` used by theme deployment is intentionally not reused. EasyStore's documented customer API authenticates with the `EasyStore-Access-Token` header, so this sync has its own least-privilege customer-read credential.

## Identity and normalization

The normalized mobile number is the only CRM identity key. Email is synchronized as contact data but is never used to decide which HubSpot record belongs to an EasyStore customer.

`scripts/easystore_hubspot_sync.py` normalizes EasyStore `phone` values to an E.164-style `+<country code><subscriber>` value. It uses the customer's EasyStore ISO `country_code` when available and otherwise falls back to repository variable `CUSTOMER_SYNC_DEFAULT_DIAL_CODE`, which defaults to Singapore `65`.

The normalized value is written to both HubSpot `mobilephone` and `phone`. Existing HubSpot contacts are scanned and normalized the same way before matching, so harmless formatting differences do not create a second contact.

If multiple EasyStore customer records share a normalized mobile number, the most recently updated record wins for that run. If multiple HubSpot contacts already share the same normalized number, the sync does not guess: it leaves those contacts unchanged, reports the conflicting IDs and fails the run so the duplicate can be reconciled safely.

## Fields synchronized

The sync uses HubSpot standard contact properties only, so no custom HubSpot schema is required:

| EasyStore | HubSpot |
| --- | --- |
| `phone` | `phone`, `mobilephone` |
| `first_name` | `firstname` |
| `last_name` | `lastname` |
| `email` | `email` |
| `primary_address.address1/address2` | `address` |
| `primary_address.city` | `city` |
| `primary_address.province` | `state` |
| `primary_address.zip` | `zip` |
| `primary_address.country` or customer `country` | `country` |
| `primary_address.company` | `company` |

HubSpot email uniqueness is respected without turning email into an identity key. If an EasyStore email is already owned by another HubSpot contact, the sync still updates/creates the phone-identified contact but omits that conflicting email and logs a warning.

## API behavior

EasyStore customers are read page-by-page from `/api/3.0/customers.json`. HubSpot contacts are read in pages of 100 to build the normalized phone index. Creates and updates are then sent through HubSpot batch endpoints in groups of at most 100 records.

HTTP 429 and 5xx responses are retried with bounded backoff. A remote API error fails the run. Customers without a usable mobile number are skipped and counted in the run summary.
