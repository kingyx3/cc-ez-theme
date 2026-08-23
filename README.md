# Cardboard Collective EasyStore Theme

A conversion-focused EasyStore theme for Cardboard Collective, optimized for
sealed trading-card products, clear collection discovery, and responsive
shopping on desktop and mobile.

## Documentation

- [Theme guide](docs/THEME_GUIDE.md) — architecture, customization, navigation,
  product organization, and maintenance
- [Packaging and deployment](docs/PACKAGING_AND_DEPLOYMENT.md) — validation,
  ZIP generation, GitHub artifacts, and EasyStore upload
- [EasyStore API deployment](docs/EASYSTORE_API_DEPLOYMENT.md) — automatic
  post-package imports and publishing, theme id resolution, branch/version
  naming, token setup, and troubleshooting
- [Source attribution](docs/SOURCE_ATTRIBUTION.md) — how a Cloudflare click
  becomes the acquisition channel on a HubSpot contact, what that claim covers,
  and the one manual EasyStore setup step it needs
- [Attribution runtime constraints](docs/ATTRIBUTION_RUNTIME_CONSTRAINTS.md) —
  production checkout/account assumptions, HubSpot storefront tracking, and the
  temporary Reality Fracture Worker handover

## Repository layout

```text
.
├── .github/workflows/       GitHub Actions validation, packaging, and deployment
├── docs/                    Maintainer documentation (never packaged)
├── scripts/                 Theme validation and deterministic ZIP builder
├── tests/                   Validator and package tests
└── theme/                   EasyStore runtime source
```

Only supported files below `theme/` are copied into the upload ZIP. Repository
documentation, tests, scripts, workflow files, build output, and other
development files are deliberately excluded.

## Quick validation

```bash
python scripts/theme_ci.py check theme
python -m unittest discover -s tests -v
python scripts/theme_ci.py package theme cc-ez-theme.zip
```

The generated ZIP has one EasyStore-compatible wrapper:

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

Do not zip the repository or the `theme/` folder manually. Use the packaging
script or download the `cc-ez-theme` artifact produced by GitHub Actions.
