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

Use `scripts/theme_ci.py` or the GitHub Actions artifact.

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
python scripts/theme_ci.py check theme
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
python -m unittest discover -s tests -v
```

CI coverage:

```bash
python -m coverage run -m unittest discover -s tests -v
python -m coverage report
```

The coverage configuration enforces 100% line and branch coverage for the
packaging and validation code. This tests the repository tooling, not every
possible EasyStore runtime condition.

## 6. Build the upload ZIP

```bash
python scripts/theme_ci.py package theme cc-ez-theme.zip
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
python -c "from scripts.theme_ci import validate_archive; print(validate_archive('cc-ez-theme.zip'))"
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

The `Package EasyStore theme` workflow runs on pushes to every branch and through manual workflow dispatch.

Its jobs are chained in this order:

1. `test` validates the real theme and enforces coverage;
2. `package` builds the normal downloadable `cc-ez-theme` artifact;
3. `deploy` starts only after `package` succeeds, only when the run is on `main`, and imports an unpublished deployment candidate into EasyStore when `EASYSTORE_ADMIN_TOKEN` is configured.

On any branch other than `main`, the workflow stops after `package`. The `cc-ez-theme` artifact is still built and uploaded, and `deploy` is skipped, so no EasyStore import happens from feature or release branches.

The normal package job:

1. builds `cc-ez-theme.zip`;
2. extracts it into an artifact staging directory;
3. validates the extracted theme;
4. uploads the staging directory as the `cc-ez-theme` artifact.

GitHub itself creates the downloaded artifact ZIP. Uploading the extracted
wrapper prevents an incorrect ZIP-inside-ZIP structure.

The deploy job creates a separate temporary staging copy. It stamps branch/run/commit identity into the theme metadata, validates that staging copy, creates a deployment ZIP whose internal root remains `cc-ez-theme/`, and sends it to the EasyStore admin theme import endpoint.

See [EasyStore API deployment](EASYSTORE_API_DEPLOYMENT.md) for the credential and naming rules.

## 9. Automatic import and manual fallback

When `EASYSTORE_ADMIN_TOKEN` exists, every successful workflow run on `main` automatically attempts an EasyStore import after packaging. Runs on other branches stop at the ZIP. The workflow does not intentionally publish the imported theme.

In EasyStore:

1. Open **Channels → Online Store → Themes**.
2. Find the imported theme using the branch/run/SHA identity shown in the GitHub job summary.
3. Open **Edit source** and confirm files were imported.
4. Preview homepage, collection, product, search, cart, account, and mobile navigation behavior.
5. Publish only after preview acceptance.

If automatic import is unavailable, use the package artifact as a fallback:

1. Open the successful `Package EasyStore theme` workflow run.
2. Download the `cc-ez-theme` artifact.
3. Do not extract and recompress it.
4. In EasyStore, choose **More actions → Upload theme**.
5. Upload the downloaded artifact ZIP.

If `EASYSTORE_ADMIN_TOKEN` is missing, packaging still succeeds and the deploy job records a warning instead of attempting an unauthenticated request.

## 10. Release acceptance checklist

- [ ] The workflow test job succeeded.
- [ ] The package job succeeded.
- [ ] The artifact has one `cc-ez-theme/` root.
- [ ] There is no nested ZIP.
- [ ] For a `main` run, the deploy job imported the expected branch/run/SHA candidate, or manual fallback was used intentionally. For a non-`main` run, the deploy job was skipped and the artifact was used for manual upload if a preview was needed.
- [ ] EasyStore Edit source shows populated runtime directories.
- [ ] The unpublished preview renders.
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

### Automatic import was skipped

The `EASYSTORE_ADMIN_TOKEN` repository secret is not configured. Add it under **Settings → Secrets and variables → Actions**. The next successful workflow run will attempt the import.

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
