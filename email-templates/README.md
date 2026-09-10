# EasyStore email templates

This directory is the Git source of truth for EasyStore transactional email templates managed through the Admin API.

Each template lives in its own directory named after the EasyStore template slug used by `/admin/v2/store/settings/templates/{slug}`.

## Structure

```text
email-templates/
├── order-cancel/
│   ├── template.json   # subject, enabled state, CCs, and template attributes
│   ├── template.html   # HTML/Liquid body
│   └── plain.txt       # plain-text body
└── payment-successful/
    ├── template.json
    ├── template.html
    └── plain.txt
```

The GitHub Actions workflow assembles the EasyStore JSON payload with `jq`, keeping HTML and plain text readable and reviewable instead of storing them as escaped JSON strings.

## Validate locally

At minimum, validate each metadata JSON file and make sure all three source files are present:

```bash
for dir in email-templates/*/; do
  jq empty "${dir}template.json"
  test -s "${dir}template.html"
  test -s "${dir}plain.txt"
done
```

The CI workflow performs the full payload-generation validation on pull requests.

## Deployment

`.github/workflows/easystore-email-templates.yml` follows the existing EasyStore admin/theme deployment convention in this repository:

- pushes on `main` deploy through the GitHub `prod` environment;
- pushes on any non-`main` branch deploy through the GitHub `dev` environment.

A merge into a non-`main` branch therefore deploys the merged branch state to dev. A merge into `main` deploys production. Manual runs use the selected workflow ref in the same way.

Both GitHub environments use the same configuration names, with environment-specific values:

- Secret `EASYSTORE_ADMIN_TOKEN`
- Variable `EASYSTORE_POD_ID`
- Variable `EASYSTORE_STORE_DOMAIN`

If the selected environment is missing any required value, validation still succeeds but the automatic EasyStore deployment is skipped with a warning, matching the existing EasyStore admin deployment workflow.

The EasyStore Admin endpoint used here is not a documented public API. Treat it as an internal integration: tokens may expire and request/header requirements may change when EasyStore changes its admin application.
