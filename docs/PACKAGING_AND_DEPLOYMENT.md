# Packaging and Deployment

## 1. Important rule

Do not upload a ZIP of the repository and do not manually zip `theme/`.

EasyStore expects a single top-level directory containing the runtime theme
directories. The supported package shape is:

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

Use `scripts/theme/theme_ci.py` or the GitHub Actions artifact.

## 2. Why repository documentation is safe

Documentation is stored in `README.md` and `docs/`, outside the `theme/`
source directory.

The packager:

1. Receives `theme/` as its source.
2. Creates the `cc-ez-theme/` wrapper.
3. Creates only the eight required runtime directories.
4. Copies only supported files beneath those directories.
5. Validates the completed ZIP.

Therefore repository documentation, workflows, tests, and scripts cannot be
included by adding files at repository root.

## 3. Local prerequisites

- Python 3.13 is used in CI.
- The package builder itself uses only the Python standard library.
- Coverage is required only for the CI test suite.

Install development dependencies when needed:

```bash
python -m pip install --requirement requirements-dev.txt
```

## 4. Validate the theme

```bash
python scripts/theme/theme_ci.py check theme
```

Validation checks include:

- all eight required directories;
- required settings, layout, and homepage files;
- storefront/editor asset filename parity;
- forbidden metadata;
- symbolic links;
- UTF-8 readability of JSON and Liquid;
- JSON syntax;
- section schema syntax and shape;
- literal local asset, section, and snippet references;
- balanced Liquid blocks — an unclosed or wrongly closed `if`, `unless`, `for`,
  `case`, `capture`, `comment` or `schema` is invisible to every other check
  here and only surfaces when EasyStore compiles the theme, by which point the
  upload has failed or the storefront is serving the platform's unavailable
  page;
- one line per Liquid tag, since a tag written across several lines parses on
  some Liquid engines and not others.

## 5. Run tests

Basic tests:

```bash
python -m unittest discover -s tests/theme -v
```

CI coverage:

```bash
python -m coverage run -m unittest discover -s tests/theme -v
python -m coverage report
```

The coverage configuration enforces 100% line and branch coverage for the
packaging and validation code. This tests the repository tooling, not every
possible EasyStore runtime condition.

`.coveragerc` measures only `scripts/theme/`. The CRM sync scripts under
`scripts/crm/` ship no theme code and are not imported by `tests/theme/`; they are compiled and
tested by the `Validate CRM sync` job instead. See
`docs/CUSTOMER_CRM_SYNC.md`.

## 6. Build the upload ZIP

```bash
python scripts/theme/theme_ci.py package theme cc-ez-theme.zip
```

The command:

- validates the source before writing;
- emits deterministic timestamps and ordering;
- uses a single `cc-ez-theme/` wrapper;
- filters non-runtime files;
- checks archive structure;
- checks duplicate and unsafe paths;
- verifies ZIP CRC integrity;
- prints the SHA-256 digest.

## 7. Inspect the ZIP

```bash
python -m zipfile -l cc-ez-theme.zip
python -c "from scripts.theme.theme_ci import validate_archive; print(validate_archive('cc-ez-theme.zip'))"
```

The second command should print:

```text
[]
```

The archive must not contain:

- `README.md`;
- `docs/`;
- `.github/`;
- `scripts/`;
- `tests/`;
- `.git/`;
- `__MACOSX/`;
- `.DS_Store`;
- an outer repository directory;
- a second nested ZIP.

## 8. GitHub Actions behavior

The `Package EasyStore theme` workflow runs on pushes to every branch and through manual workflow dispatch, but only for pushes that touch the theme or the tooling that gates it:

- `theme/**` — the theme itself;
- `tests/theme/**`, `.coveragerc`, `requirements-dev.txt` — the suite and dependencies that must pass before packaging;
- `scripts/theme/theme_ci.py`, `scripts/theme/easystore_publish.py` — the validation/packaging and publish tooling the jobs run;
- `.github/workflows/package-theme.yml` — the workflow itself.

CI is bifurcated between the two independent products in this repository: the theme and the EasyStore→HubSpot CRM sync. A push that only changes CRM sync sources (`scripts/crm/easystore_hubspot_*.py`, `tests/crm/**`, `docs/CUSTOMER_CRM_SYNC.md`) does not repackage, import, or republish the storefront theme — it is gated by `Validate CRM sync` instead. Use `workflow_dispatch` to package or deploy the current theme from a commit that changed nothing theme-related.

Its jobs are chained in this order:

1. `test` validates the real theme and enforces coverage;
2. `package` builds the normal downloadable `cc-ez-theme` artifact;
3. `deploy` starts after `package` succeeds, imports a deployment candidate into EasyStore, publishes it, and then checks that EasyStore reports it as the live theme.

`deploy` runs on every branch and selects its GitHub environment from the branch: `main` uses `prod` (the live storefront) and every other branch uses `dev` (the dev storefront). Pushing a feature branch therefore replaces the live theme on the **dev** store. Only theme sources and the tooling that gates them trigger it (see the `paths` filter in the workflow).

The normal package job:

1. builds `cc-ez-theme.zip`;
2. extracts it into an artifact staging directory;
3. validates the extracted theme;
4. uploads the staging directory as the `cc-ez-theme` artifact.

GitHub itself creates the downloaded artifact ZIP. Uploading the extracted
wrapper prevents an incorrect ZIP-inside-ZIP structure.

The deploy job creates a separate temporary staging copy. It stamps branch/run/commit identity into the theme metadata, validates that staging copy, creates a deployment ZIP whose internal root remains `cc-ez-theme/`, sends it to the EasyStore admin theme import endpoint, resolves the imported theme's id, and publishes that theme.

See [EasyStore API deployment](EASYSTORE_API_DEPLOYMENT.md) for the credential, naming, theme id resolution, and publish rules.

## 9. Automatic import, publish, and manual fallback

Every workflow run automatically imports the theme after packaging and then publishes it. A run on `main` changes the live storefront; a run on any other branch changes the dev storefront.

A green deploy means the theme is live. After the publish request the job lists the store's themes (retrying for up to about 25 seconds) and fails unless EasyStore reports the imported theme as the live one (`is_enabled: 1`; the publish request moves that flag from the previous theme to the imported one). EasyStore accepting the publish request with a 2xx is not enough on its own.

The publish step never uses a stored theme id. After the import it reads the EasyStore theme listing and matches the branch/run/SHA identity this run stamped into the theme, so the `PUT` that publishes always targets the theme that was just imported. If nothing matches, or two themes claim the same identity, the job fails without publishing.

To check what a run deployed, in the store's admin:

1. Open **Channels → Online Store → Themes**.
2. Find the theme named with the branch/run/SHA identity shown in the GitHub job summary; it should be the live (current) theme.
3. Open **Edit source** and confirm files were imported.
4. Preview homepage, collection, product, search, cart, account, and mobile navigation behavior.

If automatic import is unavailable, use the package artifact as a fallback:

1. Open the successful `Package EasyStore theme` workflow run.
2. Download the `cc-ez-theme` artifact.
3. Do not extract and recompress it.
4. In EasyStore, choose **More actions → Upload theme**.
5. Upload the downloaded artifact ZIP.

If `EASYSTORE_ADMIN_TOKEN`, `EASYSTORE_POD_ID` or `EASYSTORE_STORE_DOMAIN` is missing from the selected GitHub environment, packaging still succeeds but the deploy job **fails** with an error instead of attempting an unauthenticated request. Nothing is imported or published, and the run is not green.

## 10. Release acceptance checklist

- [ ] The workflow test job succeeded.
- [ ] The package job succeeded.
- [ ] The artifact has one `cc-ez-theme/` root.
- [ ] There is no nested ZIP.
- [ ] The deploy job imported the expected branch/run/SHA candidate (to `prod` for `main`, to `dev` for any other branch), or manual fallback was used intentionally.
- [ ] The job summary shows the resolved theme id, the identity it was matched by, and a 2xx publish status, and ends with "Verified: EasyStore reports this theme as live".
- [ ] EasyStore Edit source shows populated runtime directories.
- [ ] The theme renders, whether checked as the published storefront or as an unpublished preview.
- [ ] Best Sellers, The Hobbit, Marvel, and Strixhaven each show two rows of three products on desktop.
- [ ] The Marvel Super Heroes campaign banner is absent from the homepage.
- [ ] Homepage product cards do not show the orange quick-add button.
- [ ] Product titles use available card width on desktop and mobile.
- [ ] Announcement hover/focus contrast is readable.
- [ ] Search history and the mobile drawer work with keyboard and pointer input.
- [ ] Desktop and mobile navigation show a Browse collection dropdown before Crack-a-Pack, Hobbit, Marvel, Strixhaven, and About Us.
- [ ] Hovering or focusing a parent collection in the desktop Browse menu reveals its child collection flyout.
- [ ] The footer shows Follow us and Contact Us, with no payment or quick-link blocks.
- [ ] The Terms of Service footer link opens `https://cardboard.sg/pages/terms-of-service`.
- [ ] Sold-out and sale states render correctly.
- [ ] Add to cart, cart update, and checkout handoff work.

## 11. Troubleshooting

### Deploy failed because EasyStore is not configured

`EASYSTORE_ADMIN_TOKEN` (secret) or `EASYSTORE_POD_ID` / `EASYSTORE_STORE_DOMAIN` (variables) is missing from the GitHub environment the run selected: `prod` for `main`, `dev` for other branches. Add it under **Settings → Environments**, then re-run the failed jobs.

### Publish was not verified

EasyStore accepted the publish request but its theme listing does not report the imported theme as live. The job summary shows the state EasyStore reported. If the theme resolve step could not identify the imported theme, the job fails before publishing. See [EasyStore API deployment](EASYSTORE_API_DEPLOYMENT.md).

### Automatic import returns 401 or 403

The EasyStore admin bearer token has likely expired or been revoked. Capture a fresh token from your authenticated EasyStore admin session and replace the repository secret.

### EasyStore creates a theme with no source files

Likely cause: incorrect archive envelope. Confirm the ZIP contains
`cc-ez-theme/assets/`, not `assets/` at root and not
`something/cc-ez-theme.zip`.

### EasyStore shows “temporarily unavailable”

Open the imported theme's source editor. An empty tree indicates import failure;
a populated tree suggests a Liquid/runtime issue. Check missing references,
invalid app assumptions, and the preview's affected route.

### Editor preview differs from storefront

Check that the corresponding files in `assets/` and `editor_assets/` are
identical.

### A collection section is empty

Confirm its `collection__id` matches a published EasyStore collection handle and
that the collection contains visible products.

### Catalog contains unexpected entries

EasyStore's system Catalog lists published collections automatically. Hide it
and use a curated Main Menu when the complete collection taxonomy should not be
customer-facing.

### CI rejects documentation

Documentation should not be placed inside a required runtime directory. Store
maintainer material at repository root or in `docs/`.
