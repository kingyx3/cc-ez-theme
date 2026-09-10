# EasyStore email templates

This directory is the Git source of truth for EasyStore transactional email templates managed through the Admin API.

Each template lives in its own directory named after the EasyStore template slug used by `/admin/v2/store/settings/templates/{slug}`.

## Structure

```text
email-templates/
└── payment-successful/
    ├── template.json   # subject, enabled state, CCs, and template attributes
    ├── template.html   # HTML/Liquid body
    └── plain.txt       # plain-text body
```

The GitHub Actions workflow assembles the EasyStore JSON payload with `jq`, keeping HTML and plain text readable and reviewable instead of storing them as escaped JSON strings.

## Validate locally

At minimum, validate the metadata JSON and make sure all three source files are present:

```bash
jq empty email-templates/payment-successful/template.json
test -s email-templates/payment-successful/template.html
test -s email-templates/payment-successful/plain.txt
```

The CI workflow performs the full payload-generation validation on pull requests.

## Deployment

`.github/workflows/easystore-email-templates.yml` validates templates on pull requests. After changes under `email-templates/**` are merged to `main`, the workflow deploys all managed templates to EasyStore. It can also be run manually for one template or all templates.

Required GitHub Actions secret:

- `EASYSTORE_ADMIN_TOKEN` — bearer token accepted by `api.easystore.co` for the EasyStore Admin API.

Optional repository variables (defaults match the current Cardboard Collective store routing):

- `EASYSTORE_DEFAULT_DOMAIN` — defaults to `cardboardcollective.easy.co`.
- `EASYSTORE_POD_ID` — defaults to `1007`.

The EasyStore Admin endpoint used here is not a documented public API. Treat it as an internal integration: tokens may expire and request/header requirements may change when EasyStore changes its admin application.
