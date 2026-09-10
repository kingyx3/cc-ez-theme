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

`.github/workflows/easystore-email-templates.yml` uses two deployment targets:

- **Development:** when a pull request containing email-template changes is merged into any branch other than `main`, the merged base-branch state is deployed to the dev EasyStore store.
- **Production:** when email-template changes reach `main`, the resulting `push` deploys the `main` state to the production EasyStore store.

An ordinary push to a non-`main` branch does not deploy. This keeps development deployment tied to completed merges rather than every feature-branch commit.

The workflow can also be run manually for one template or all templates, with an explicit `dev` or `production` target.

### Production configuration

Required GitHub Actions secret:

- `EASYSTORE_ADMIN_TOKEN` — production bearer token accepted by `api.easystore.co` for the EasyStore Admin API.

Optional repository variables (defaults match the current Cardboard Collective production routing):

- `EASYSTORE_DEFAULT_DOMAIN` — defaults to `cardboardcollective.easy.co`.
- `EASYSTORE_POD_ID` — defaults to `1007`.

### Development configuration

Development deliberately has no production fallback. Configure all of the following before merging template changes into a non-`main` branch:

- Secret `EASYSTORE_DEV_ADMIN_TOKEN` — bearer token for the dev EasyStore store.
- Variable `EASYSTORE_DEV_DEFAULT_DOMAIN` — dev store EasyStore default domain.
- Variable `EASYSTORE_DEV_POD_ID` — dev store pod ID.

If any dev setting is missing, the dev deployment fails before making a PUT request rather than falling back to production routing.

The EasyStore Admin endpoint used here is not a documented public API. Treat it as an internal integration: tokens may expire and request/header requirements may change when EasyStore changes its admin application.
