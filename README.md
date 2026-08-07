# Cardboard Collective EasyStore Theme

A conversion-focused EasyStore theme for Cardboard Collective, optimized for
sealed trading-card products, clear collection discovery, and responsive
shopping on desktop and mobile.

## Documentation

- [Theme guide](docs/THEME_GUIDE.md) — architecture, customization, navigation,
  product organization, and maintenance
- [Packaging and deployment](docs/PACKAGING_AND_DEPLOYMENT.md) — validation,
  ZIP generation, GitHub artifacts, and EasyStore upload
- [EasyStore API deployment](docs/EASYSTORE_API_DEPLOYMENT.md) — manual GitHub
  Actions import, bearer-token setup, and API troubleshooting

## Repository layout

```text
.
├── .github/workflows/       GitHub Actions validation and packaging
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
script or download the `cc-ez-theme` artifact produced after a merge to `main`.
