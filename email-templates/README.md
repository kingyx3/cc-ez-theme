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

`.github/workflows/easystore-email-templates.yml` follows the same GitHub Environment convention as the existing EasyStore theme/admin deployment workflow:

- `main` deploys through the GitHub `prod` environment.
- Any non-`main` branch deploys through the GitHub `dev` environment.

A PR merge into a non-`main` branch therefore deploys the merged branch state to dev through the resulting branch push. A merge into `main` deploys production.

Manual runs use the selected workflow ref in the same way: `main` uses `prod`, while another branch uses `dev`.

Both GitHub environments use the same configuration names; their values differ by environment:

- Secret `EASYSTORE_ADMIN_TOKEN`
- Variable `EASYSTORE_POD_ID`
- Variable `EASYSTORE_STORE_DOMAIN`

If the selected environment is missing any required value, validation still succeeds but the automatic EasyStore deployment is skipped with a warning, matching the repository's existing admin deployment behavior.

The EasyStore Admin endpoint used here is not a documented public API. Treat it as an internal integration: tokens may expire and request/header requirements may change when EasyStore changes its admin application.
