# Cardboard Collective EasyStore Theme

Production storefront theme and supporting automation for Cardboard Collective on EasyStore. The repository contains the EasyStore theme, validation/packaging tooling, browser tests, Cloudflare workers, CRM synchronization tooling, and the operational documentation required to release them safely.

## Production warning

**Treat merges to `main` as production releases for theme changes.** The theme packaging workflow can import and publish a successful `main` build automatically when `EASYSTORE_ADMIN_TOKEN` is configured and publishing is enabled. Shared commerce changes must be previewed from a non-`main` branch before merge.

See [Theme production safety](docs/THEME_PRODUCTION_SAFETY.md) and the [Operations runbook](docs/OPERATIONS_RUNBOOK.md) before changing product cards, product forms, cart behavior, checkout entry points, global assets, packaging, deployment, or production integrations.

## Repository contents

```text
.
├── .github/workflows/       CI, packaging, deployment, sync, and observability
├── cloudflare/               Cloudflare Workers and worker-specific docs/tests
├── crm_tests/                CRM synchronization tests
├── docs/                     Maintainer and operations documentation
├── e2e/                      Playwright storefront tests
├── scripts/                  Validation, packaging, publishing, and sync tooling
├── tests/                    Theme validator/package tests
└── theme/                    EasyStore runtime source
```

Only supported files below `theme/` are copied into the EasyStore upload ZIP. Repository documentation, tests, scripts, workflows, and other development files are excluded from the package.

The storefront and editor configuration mirrors (`theme/config/settings_data.json` and `theme/editor_config/settings_data.json`) must remain byte-for-byte identical. The test suite enforces this invariant.

## Prerequisites

For theme validation and packaging:

- Python 3.13 (the version used in CI)
- `pip`

For browser tests:

- Node.js and npm
- Playwright browser binaries

Install local dependencies:

```bash
python -m pip install --requirement requirements-dev.txt
npm install
npx playwright install
```

Worker directories under `cloudflare/` have their own `package.json` files and setup instructions. Install dependencies inside the worker you are modifying rather than assuming the repository-root npm dependencies cover worker development.

## Local validation

Run the theme validator and unit suite before opening a pull request:

```bash
python scripts/theme_ci.py check theme
python -m unittest discover -s tests -v
```

Run the same coverage gate used for the repository tooling:

```bash
python -m coverage run -m unittest discover -s tests -v
python -m coverage report
```

Build and validate the production upload artifact:

```bash
python scripts/theme_ci.py package theme cc-ez-theme.zip
python -m zipfile -l cc-ez-theme.zip
python -c "from scripts.theme_ci import validate_archive; print(validate_archive('cc-ez-theme.zip'))"
```

The final command must print `[]`.

For storefront browser tests, `E2E_BASE_URL` defaults to `https://cardboard.sg`:

```bash
npm run test:e2e:smoke
npm run test:e2e:a11y
npm run test:e2e
```

To test an unpublished preview or another environment:

```bash
E2E_BASE_URL=https://example-preview-host npm run test:e2e:smoke
```

Do not point destructive or state-changing test work at production unless the test is explicitly designed and reviewed for production safety.

## Packaging contract

Do not zip the repository or `theme/` manually. Use `scripts/theme_ci.py` or the `cc-ez-theme` GitHub Actions artifact.

The generated ZIP must contain exactly one EasyStore-compatible wrapper:

```text
cc-ez-theme/
├── assets/
├── config/
├── editor_assets/
├── editor_config/
├── layout/
├── sections/
├── snippets/
└── templates/
```

See [Packaging and deployment](docs/PACKAGING_AND_DEPLOYMENT.md) for the complete artifact and release contract.

## Documentation

Start with the [documentation index](docs/README.md).

Key references:

- [Theme guide](docs/THEME_GUIDE.md) — theme architecture, customization, navigation, product organization, and maintenance
- [Theme production safety](docs/THEME_PRODUCTION_SAFETY.md) — mandatory design invariants and pre-production review matrix
- [Operations runbook](docs/OPERATIONS_RUNBOOK.md) — release, preview, rollback, incident response, and operational ownership
- [Packaging and deployment](docs/PACKAGING_AND_DEPLOYMENT.md) — validation, ZIP generation, GitHub artifacts, import, and publish behavior
- [EasyStore API deployment](docs/EASYSTORE_API_DEPLOYMENT.md) — deployment credentials, theme identity resolution, naming, and troubleshooting
- [Customer CRM sync](docs/CUSTOMER_CRM_SYNC.md) — EasyStore-to-HubSpot synchronization behavior and operations
- [Marketing links](docs/MARKETING_LINKS.md) — tracked campaign links
- [Source attribution](docs/SOURCE_ATTRIBUTION.md) — customer acquisition attribution
- [Order source attribution](docs/ORDER_SOURCE_ATTRIBUTION.md) — per-order attribution and production smoke tests

Cloudflare worker documentation lives beside each worker under `cloudflare/*/README.md`.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before making changes. Pull requests should be small, testable, and explicit about production impact, preview evidence, deployment behavior, and rollback.

## Security

Do not commit API tokens, session credentials, customer data, webhook secrets, or production exports. Follow [SECURITY.md](SECURITY.md) for vulnerability reporting and credential-handling expectations.

## Release model

- Feature branches validate and package but do not publish the EasyStore theme automatically.
- `main` is the production release branch for theme changes.
- When `EASYSTORE_ADMIN_TOKEN` is configured, a successful `main` workflow can import and publish the just-built theme.
- `EASYSTORE_PUBLISH=false` changes the automated behavior to import-only so the resulting theme remains an unpublished preview candidate.
- A failed validation, package, import, identity-resolution, or publish step is a failed release and must be investigated before retrying or merging follow-up changes.

The [Operations runbook](docs/OPERATIONS_RUNBOOK.md) is the authoritative release checklist for maintainers.
