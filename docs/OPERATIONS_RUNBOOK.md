# Production operations runbook

This runbook is the maintainer checklist for previewing, releasing, rolling back, and responding to incidents across the EasyStore theme and the production integrations in this repository.

## 1. Release ownership and production boundaries

The repository contains multiple independently deployable products:

- the EasyStore storefront theme under `theme/`;
- Cloudflare Workers under `cloudflare/`;
- EasyStore/HubSpot CRM synchronization tooling under `scripts/` and `crm_tests/`;
- attribution and other scheduled/integration workflows under `.github/workflows/`.

Do not assume a successful check for one product validates another. Use the workflow and test suite for the subsystem you changed.

For the theme, `main` is the production release branch. When `EASYSTORE_ADMIN_TOKEN` is configured and publishing is enabled, the package workflow can import and publish a successful `main` build automatically. Non-`main` branches package without automatic publish and are the correct place to produce preview candidates.

## 2. Before opening a pull request

For theme changes:

```bash
python scripts/theme_ci.py check theme
python -m unittest discover -s tests -v
python -m coverage run -m unittest discover -s tests -v
python -m coverage report
python scripts/theme_ci.py package theme cc-ez-theme.zip
python -c "from scripts.theme_ci import validate_archive; print(validate_archive('cc-ez-theme.zip'))"
```

Archive validation must print `[]`.

For storefront-visible work, run relevant Playwright suites against the intended preview target:

```bash
E2E_BASE_URL=https://preview-host npm run test:e2e:smoke
E2E_BASE_URL=https://preview-host npm run test:e2e:a11y
```

Run the full browser suite when the change is broad enough to affect multiple surfaces, navigation, shared components, or global assets.

For Cloudflare or CRM changes, use the component README and the workflow that owns that component. Document any new binding, secret, variable, migration, schedule, external API scope, or operational dependency in the same pull request.

## 3. Preview procedure for theme changes

Shared commerce changes require an unpublished EasyStore preview before merge.

1. Push the feature branch and wait for its validation/package workflow to pass.
2. Download the `cc-ez-theme` artifact from the successful run, or use an intentionally imported unpublished candidate when the deployment workflow supports that mode.
3. Do not extract and recompress the artifact.
4. Upload/import the artifact as an unpublished EasyStore theme.
5. Verify the imported source directories are populated.
6. Preview all surfaces named in `THEME_PRODUCTION_SAFETY.md` that the change can affect.
7. Test desktop and mobile, logged-out and logged-in states where relevant, variant/sale/sold-out states, add-to-cart, cart edits, and checkout handoff.
8. Confirm installed app snippets and hooks still work.
9. Record the preview result and rollback target in the pull request.

Static validation does not replace the preview. It cannot prove live asset order, EasyStore runtime behavior, installed apps, customer/account data, or platform responses.

## 4. Pre-merge release gate

Before merging a production theme change, confirm all of the following:

- [ ] CI checks for the changed subsystem pass.
- [ ] The exact packaged artifact was inspected or previewed.
- [ ] The EasyStore package has one `cc-ez-theme/` wrapper and no nested ZIP.
- [ ] The storefront/editor config mirrors remain identical.
- [ ] Relevant Playwright/manual checks pass against the preview.
- [ ] No new secret, token, customer data, private payload, or generated production export is tracked.
- [ ] Any new repository secret/variable or third-party configuration is documented.
- [ ] The rollback target is identified by commit/theme version and is known good.
- [ ] The pull request explains production impact and expected workflow behavior after merge.

If any item is unknown, do not treat the release as ready.

## 5. Theme release procedure

1. Merge only after preview acceptance.
2. Watch the `Package EasyStore theme` workflow on the merge commit.
3. Confirm `test` succeeds.
4. Confirm `package` succeeds and produces the expected artifact.
5. On `main`, confirm the deploy job either:
   - imports and publishes the intended candidate; or
   - intentionally imports without publishing because `EASYSTORE_PUBLISH=false`; or
   - records that deployment was skipped because credentials are intentionally unavailable.
6. When publishing is expected, verify the job summary resolves the imported theme by the run/branch/commit identity and reports a successful publish/readback.
7. Smoke-test the live storefront after publish: homepage, collection, product, search, cart, account/navigation, mobile navigation, add-to-cart, cart update, and checkout handoff.

A workflow failure after merge is a production release failure. Investigate the failing stage before retrying or layering unrelated fixes on top.

## 6. Rollback procedure

A rollback should restore a known-good storefront, not merely remove the newest lines from `main`.

1. Identify the last known-good production commit/theme and the incident start time.
2. If the current theme is actively harming checkout or storefront usability, prioritize restoring the known-good theme in EasyStore.
3. Revert the offending Git change in a focused pull request so repository state matches the restored production behavior.
4. Run the normal validation/package checks on the revert.
5. Confirm the resulting `main` workflow publishes the intended rollback candidate, or perform the documented manual fallback when automatic deployment is unavailable.
6. Smoke-test the restored live storefront.
7. Preserve failing workflow logs, screenshots, and timestamps needed for root-cause analysis, but redact secrets/customer data before attaching evidence to GitHub.

Do not reintroduce experimental hooks or partial client-side interception as part of an emergency rollback.

## 7. Incident response

Use this sequence for production regressions, broken checkout/cart behavior, failed publishing, attribution failures, CRM sync failures, or Worker incidents.

### Contain

- Disable or revert the narrowest affected path.
- Restore the last known-good storefront/theme when customer purchasing is affected.
- Pause a scheduled/integration workflow if repeated execution can corrupt data or amplify the incident.
- Rotate credentials immediately if exposure is suspected; see `SECURITY.md`.

### Establish scope

Record:

- first known bad time;
- affected commit, workflow run, theme identity, Worker deployment, or sync execution;
- customer-facing symptoms;
- data/integration impact;
- whether failures are ongoing or historical.

### Preserve evidence

Keep relevant GitHub Actions run/job logs, deployment identifiers, EasyStore theme identity, Worker logs, and sanitized example payloads. Do not paste unredacted credentials or customer records into GitHub.

### Recover

Restore the last known-good version or disable the failing integration. Verify recovery using the same customer-facing or data-path checks that detected the incident.

### Follow up

Document root cause, why existing validation did not catch it, the permanent fix, and any test/runbook change that prevents recurrence.

## 8. Credential and configuration changes

Repository and platform secrets are operational dependencies. When changing them:

- make the change in the platform secret store, not in tracked files;
- document the secret/variable name, purpose, scope, and rotation owner without documenting its value;
- use least privilege;
- verify the consuming workflow with a non-destructive run when possible;
- rotate immediately after suspected exposure.

Theme deployment behavior specifically depends on `EASYSTORE_ADMIN_TOKEN` and `EASYSTORE_PUBLISH`. Detailed token and theme-resolution behavior is documented in `EASYSTORE_API_DEPLOYMENT.md`.

## 9. Manual packaging/deployment fallback

When automatic import is unavailable but a release is still intentional:

1. Use a successful package artifact from the exact commit being released.
2. Confirm its wrapper/CRC validation.
3. Upload the downloaded artifact ZIP directly to EasyStore without extracting/recompressing it.
4. Keep it unpublished until preview checks pass, unless this is an emergency rollback to a previously verified artifact.
5. Record the manual action and released commit in the pull request or incident record.

Never construct a release ZIP by manually zipping the repository or `theme/` directory.

## 10. Operational documentation ownership

Update this runbook whenever release triggers, secrets/variables, rollback mechanics, preview behavior, or production ownership changes. Update the subsystem document when integration-specific behavior changes. The root `README.md` and `docs/README.md` should remain concise entry points that link to the authoritative procedure.