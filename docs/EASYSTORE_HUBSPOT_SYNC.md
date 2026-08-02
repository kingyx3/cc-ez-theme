# EasyStore customer sync to HubSpot

## Conclusion

A fully unattended EasyStore customer sync requires authenticated access to the EasyStore Admin API. EasyStore's public authentication flow issues that access through an EasyStore app installation and OAuth authorization. GitHub Actions can host the scheduled job, but it cannot bypass EasyStore authentication.

There are therefore two supported operating modes in this branch.

## 1. Existing EasyStore access token: automated API sync

Use this when the store already has a valid EasyStore access token with customer-read permission. No new storefront code is required, but the token must have been issued through EasyStore's supported authorization process.

Repository secrets:

- `EASYSTORE_SHOP`: store hostname, such as `example.easy.co`
- `EASYSTORE_ACCESS_TOKEN`: token allowed to read customers
- `HUBSPOT_ACCESS_TOKEN`: HubSpot private-app token with contact read/write access

Before enabling the hourly schedule, run the workflow manually in this order:

1. `probe` — checks both APIs with minimal reads and writes nothing.
2. `dry-run` — downloads all EasyStore customers and validates the HubSpot mapping without writing contacts.
3. `sync` — performs the batch upsert.

The scheduled workflow runs hourly at minute 17.

## 2. No EasyStore app or token: manual CSV bridge

EasyStore supports exporting customers as CSV or Excel from the admin customer screen. The script can consume the CSV directly, so no EasyStore app or API token is needed:

```bash
export HUBSPOT_ACCESS_TOKEN='...'
python scripts/sync_easystore_customers_to_hubspot.py \
  --source csv \
  --csv ~/Downloads/easystore-customers.csv \
  --dry-run

python scripts/sync_easystore_customers_to_hubspot.py \
  --source csv \
  --csv ~/Downloads/easystore-customers.csv
```

The parser recognizes common EasyStore headings such as `Email`, `First Name`, `Last Name`, and `Phone`.

This route is not a true continuous sync: someone must export the latest file and run the command. Do not commit customer exports to this repository because they contain personal data.

## Options considered

### Theme JavaScript

Not suitable for a complete sync. Theme code only sees visitors using the storefront, cannot enumerate historical customers, and must not contain private HubSpot credentials.

### EasyStore webhooks

More efficient than polling, but webhook registration and authenticated customer access are app/API features. They still require an EasyStore app authorization path and a public HTTPS receiver.

### Browser automation of EasyStore Admin

Technically possible but not recommended. It is brittle, may conflict with MFA/session controls, and would require storing administrative credentials. It is deliberately not implemented here.

### Native/manual HubSpot import

For occasional migration, exporting customers from EasyStore and importing the file directly in HubSpot may be simpler than running this script. The script is useful when repeatable field normalization and upsert behavior are desired.

## Data mapping

| EasyStore | HubSpot |
| --- | --- |
| Email | `email` and upsert identifier |
| First Name | `firstname` |
| Last Name | `lastname` |
| Phone | `phone` |

Customers without email are skipped. Email is used as the identifier, so review HubSpot's email-upsert behavior before adding more properties.

## Security

- Keep API tokens only in GitHub Actions secrets or local environment variables.
- Use the smallest available scopes.
- Never place either token in theme Liquid or browser JavaScript.
- Never commit exported customer data.
- Run `probe` and `dry-run` before enabling scheduled writes.
