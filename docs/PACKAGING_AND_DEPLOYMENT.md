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
- literal local asset, section, and snippet references.

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

The `Package EasyStore theme` workflow runs:

- on pushes to any branch;
- through manual workflow dispatch.

The test job always validates the real theme and enforces coverage.

The package job runs after successful tests for pushes to any branch and manual
runs. It:

1. builds `cc-ez-theme.zip`;
2. extracts it into an artifact staging directory;
3. validates the extracted theme;
4. uploads the staging directory as the `cc-ez-theme` artifact.

GitHub itself creates the downloaded artifact ZIP. Uploading the extracted
wrapper prevents an incorrect ZIP-inside-ZIP structure.

## 9. Download and upload

After pushing the branch you want to package:

1. Open the successful `Package EasyStore theme` workflow run.
2. Download the `cc-ez-theme` artifact.
3. Do not extract and recompress it.
4. In EasyStore, open **Channels → Online Store → Themes**.
5. Choose **More actions → Upload theme**.
6. Upload the downloaded artifact ZIP.
7. Keep the imported theme unpublished initially.
8. Open **Edit source** and confirm files were imported.
9. Preview homepage, collection, product, search, cart, account, and mobile
   navigation behavior.
10. Publish only after preview acceptance.

## 10. Release acceptance checklist

- [ ] Pull-request CI succeeded.
- [ ] The workflow for the intended branch succeeded.
- [ ] The artifact has one `cc-ez-theme/` root.
- [ ] There is no nested ZIP.
- [ ] EasyStore Edit source shows populated runtime directories.
- [ ] The unpublished preview renders.
- [ ] Best Sellers, The Hobbit, Marvel, and Strixhaven each show two rows of three products on desktop.
- [ ] The Marvel Super Heroes campaign banner is absent from the homepage.
- [ ] Homepage product cards do not show the orange quick-add button.
- [ ] Product titles use available card width on desktop and mobile.
- [ ] Announcement hover/focus contrast is readable.
- [ ] Search history and the mobile drawer work with keyboard and pointer input.
- [ ] Desktop and mobile navigation show a Browse collection dropdown before Hobbit, Marvel, Strixhaven, and About Us.
- [ ] Hovering or focusing a parent collection in the desktop Browse menu reveals its child collection flyout.
- [ ] The footer shows Follow us and Contact Us, with no payment or quick-link blocks.
- [ ] The Terms of Service footer link opens `https://cardboard.sg/pages/terms-of-service`.
- [ ] Sold-out and sale states render correctly.
- [ ] Add to cart, cart update, and checkout handoff work.

## 11. Troubleshooting

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
