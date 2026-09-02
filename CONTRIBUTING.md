# Contributing

Changes to this repository can affect a live commerce storefront and production integrations. Keep changes reviewable, validate the exact subsystem you touched, and make production impact explicit in every pull request.

## Before you start

1. Read the root `README.md` and `docs/README.md`.
2. For theme changes, read `docs/THEME_PRODUCTION_SAFETY.md` and `docs/PACKAGING_AND_DEPLOYMENT.md`.
3. For integration changes, read the subsystem documentation beside or under `docs/` for that integration.
4. Work on a branch. Do not use `main` as a development or preview branch.
5. Never use real production credentials, customer records, session cookies, or private payloads as fixtures.

## Local setup

Theme tooling:

```bash
python -m pip install --requirement requirements-dev.txt
```

Browser tests:

```bash
npm install
npx playwright install
```

Cloudflare workers use separate package manifests. Run npm commands from the worker directory you are modifying.

## Required checks for theme changes

Run the validator and unit tests:

```bash
python scripts/theme_ci.py check theme
python -m unittest discover -s tests -v
```

Run the coverage gate when changing validator/packaging code:

```bash
python -m coverage run -m unittest discover -s tests -v
python -m coverage report
```

Build and validate the package:

```bash
python scripts/theme_ci.py package theme cc-ez-theme.zip
python -c "from scripts.theme_ci import validate_archive; print(validate_archive('cc-ez-theme.zip'))"
```

The archive validation command must print `[]`.

Run relevant browser coverage. The smoke suite is the minimum useful local signal for storefront changes:

```bash
npm run test:e2e:smoke
```

Use `E2E_BASE_URL` to point Playwright at the intended preview environment. The configuration defaults to the production storefront, so verify the target before running tests that may alter state.

## Production-sensitive theme changes

Changes affecting shared product cards, product forms, cart behavior, checkout entry points, global assets, or generated packages must follow `docs/THEME_PRODUCTION_SAFETY.md`.

Before merge:

- validate the proposed runtime against the last known-good production behavior;
- build and inspect the actual package artifact;
- preview the artifact as an unpublished EasyStore theme;
- test desktop and mobile paths that the change can affect;
- verify installed app hooks and realistic customer/product states;
- write down a rollback that restores the last known-good behavior.

A successful theme workflow on `main` can publish to the live storefront. There is no safe assumption that a post-merge preview window exists.

## Integration changes

For Cloudflare, CRM, attribution, Slack, or other production integrations:

- run the subsystem's unit tests and CI checks;
- document new bindings, secrets, variables, scheduled triggers, or external dependencies;
- use test/staging resources where available;
- define how to disable or roll back the integration without deleting evidence needed for incident investigation;
- avoid changing data schemas and application code in ways that make rollback impossible.

## Pull request expectations

Each pull request should explain:

- what changed and why;
- which production surfaces or integrations can be affected;
- validation performed and its result;
- preview/manual verification performed, when applicable;
- configuration, secret, variable, migration, or operational changes;
- rollback plan;
- documentation updated.

Keep unrelated refactors out of production fixes. Prefer small pull requests whose behavior can be understood from the diff and verified independently.

## Documentation changes

Update documentation in the same pull request whenever commands, prerequisites, configuration, workflows, release behavior, integration contracts, operational constraints, or support procedures change.

Do not copy secrets or sensitive production output into issue bodies, pull requests, screenshots, logs, test fixtures, or Markdown examples.

## Commit and branch hygiene

Use descriptive branch names and focused commits. Do not commit generated local test output, Playwright reports, downloaded production data, credential files, or manually built artifacts unless the repository explicitly tracks them.

## Reporting security issues

Do not open a public issue for a suspected vulnerability, exposed credential, or sensitive-data leak. Follow `SECURITY.md`.