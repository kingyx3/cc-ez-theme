# EasyStore API Deployment

The `Package EasyStore theme` GitHub Actions workflow automatically imports a theme into EasyStore and then publishes it, after validation and packaging complete successfully. This happens on every branch: `main` deploys to the live (`prod`) store and any other branch deploys to the `dev` store.

Both calls use the same EasyStore admin endpoints observed in the browser UI:

```text
POST https://api.easystore.co/admin/v2/store/themes/assets/import
PUT  https://api.easystore.co/admin/v2/store/themes/<theme id>
```

Publishing puts the imported theme live on the storefront. A run on `main` uses the `prod` GitHub environment and changes what customers see; a run on any other branch uses the `dev` environment and changes the dev storefront only. After publishing, the job asks EasyStore which theme is live and fails if it is not the imported one.

## Workflow order

For every push branch, and for a manual workflow dispatch, the workflow runs these jobs in order:

1. `test` validates the real `theme/` source and enforces the existing test coverage requirement;
2. `package` creates and validates the normal downloadable `cc-ez-theme` artifact;
3. `deploy` runs after `package` succeeds. It imports a deployment-specific ZIP into EasyStore, resolves the imported theme's id, publishes that theme, and then checks EasyStore's own report of which theme is live. The GitHub environment is chosen from the ref: `prod` for `refs/heads/main`, `dev` for every other branch. A manual `workflow_dispatch` follows the same rule.

The deploy job does not replace the normal package artifact. The artifact remains available as a manual fallback.

If `EASYSTORE_ADMIN_TOKEN`, `EASYSTORE_POD_ID` or `EASYSTORE_STORE_DOMAIN` is not configured in the selected GitHub environment, validation and packaging still succeed but the deploy job fails with an error rather than silently skipping the EasyStore requests. Once they are configured, re-run the failed jobs.

The chained path has been verified against EasyStore with a successful HTTP 200 import from the PR branch.

## Deployment naming

The source theme remains unchanged in Git. Before deployment, the workflow copies `theme/` to a temporary staging directory and stamps deployment metadata into both:

```text
config/settings_schema.json
editor_config/settings_schema.json
```

Only the staging copy is changed. The workflow updates `theme`, `theme_name` when present, and `theme_version`, then validates and packages that staging copy.

The upload ZIP filename also carries the same Git identity while preserving the required internal `cc-ez-theme/` archive root.

The deploy job runs on every branch, so each run stamps the identity for its own branch (the `main` identity below for `main`, the branch identity for anything else). The same naming makes a manually uploaded package artifact unambiguous.

### Normal branch

For a branch such as:

```text
feature/navigation-polish
```

an example deployment identity is:

```text
Theme:   CC feature-navigation-polish r451 abc1234
Version: 2.0.0+gh.451.abc1234
ZIP:     cc-ez-theme--feature-navigation-polish--r451--abc1234.zip
```

The branch portion is normalized to a filesystem-safe slug and capped at 40 characters.

### Main branch

A `main` deployment follows the same traceable convention:

```text
Theme:   CC main r451 abc1234
Version: 2.0.0+gh.451.abc1234
ZIP:     cc-ez-theme--main--r451--abc1234.zip
```

### Release branches

Branches matching either of these forms are treated as releases:

```text
release/1.4.0
release/v1.4.0
releases/1.4.0
releases/v1.4.0
```

An example is:

```text
Theme:   CC v1.4.0 abc1234
Version: 1.4.0+gh.451.abc1234
```

Pre-release versions such as `release/v1.4.0-rc.1` are also recognized.

EasyStore publicly documents the top-level `theme` field in `settings_schema.json`, but the private admin import endpoint does not have public documentation describing exactly which metadata field becomes the theme card title. For that reason the workflow supplies the deployment identity in both theme metadata and the multipart ZIP filename.

## Required GitHub secret

Create this repository Actions secret:

```text
EASYSTORE_ADMIN_TOKEN
```

Store only the token value, without the leading `Bearer ` text. The workflow adds the `Bearer` authorization scheme when sending the request.

Never commit this credential, paste it into an issue or pull request, or print it in workflow output.

## Getting the EasyStore admin bearer token

EasyStore's admin UI uses a bearer credential for authenticated admin API requests. This is an admin session credential rather than a permanent project API key, so it can expire and may need to be refreshed.

To obtain the credential from your own EasyStore admin session:

1. Sign in at `https://admin.easystore.co/` in your normal browser.
2. Open browser developer tools (`F12` or `Ctrl+Shift+I`).
3. Open the **Network** panel.
4. Open the theme uploader and perform a theme import.
5. Select the request to `/admin/v2/store/themes/assets/import`.
6. Open **Headers** and find the request header named `authorization`.
7. Its value will be in the form `Bearer <token>`.
8. Copy only the `<token>` portion into the GitHub secret `EASYSTORE_ADMIN_TOKEN`.

Treat any token copied from developer tools as a password-equivalent secret. If it is accidentally exposed, revoke the session or otherwise rotate the credential before using automation.

## Adding the secret to GitHub

In GitHub:

1. Open the repository.
2. Go to **Settings → Secrets and variables → Actions**.
3. Under **Repository secrets**, choose **New repository secret**.
4. Name it `EASYSTORE_ADMIN_TOKEN`.
5. Paste only the token value and save it.

The next successful `Package EasyStore theme` run will automatically attempt the import.

## Optional repository variables

The workflow has no built-in defaults for the store it deploys to. It reads these from the GitHub environment the run selected (`prod` for `main`, `dev` otherwise) and fails if any is missing:

```text
EASYSTORE_POD_ID=<the store's pod id>
EASYSTORE_STORE_DOMAIN=<the store's EasyStore domain>
```

Set them as environment variables under **Settings → Environments → prod / dev → Environment variables**, so the dev and prod stores stay separate.

There is no switch to import without publishing: the workflow always publishes. The `EASYSTORE_PUBLISH` variable that earlier versions read is no longer used.

The API URLs are intentionally fixed in the workflow so a secret or variable cannot silently redirect the upload to another host.

## Import request

The deployment sends the generated ZIP as multipart field `file` and includes:

```text
Authorization: Bearer <EASYSTORE_ADMIN_TOKEN>
easystore-pod-id: <pod id>
easystore-source: admin
x-easystore-infra-default-domain: <store domain>
x-easystore-infra-pod-id: <pod id>
x-easystore-infra-source: admin
idempotency-key: phase1-dummy:web:<fresh UUID>
```

Browser-only headers such as `sec-ch-ua`, `user-agent`, `referer`, and the multipart boundary are intentionally not hard-coded.

## Resolving the theme id

Publishing addresses one theme by id:

```text
PUT https://api.easystore.co/admin/v2/store/themes/<theme id>
```

The id is different for every imported theme, so the workflow discovers it after the import rather than storing it. An id copied from a browser session is not reusable: it identifies whichever theme owns it at that moment, and publishing it later would take the wrong theme live.

After a successful import the deploy job:

1. requests the theme listing at `GET https://api.easystore.co/admin/v2/store/themes`;
2. runs `scripts/theme/easystore_publish.py resolve` against both the import response and the listing response;
3. exposes the resolved id as the `theme` step output, which the publish step uses.

The resolver accepts an id only when it can tie the id back to the identity this run stamped into the package, trying in order:

1. a theme in the import response whose name matches the deployment display name;
2. a theme in the import response whose version matches the deployment version;
3. a theme in the theme listing whose name matches the deployment display name;
4. a theme in the theme listing whose version matches the deployment version;
5. the single theme described by the import response, when the response describes exactly one theme.

Name comparison ignores case and repeated whitespace. Because the display name and version both carry the run number and commit SHA, a match identifies exactly one deployment.

The resolver fails the job rather than guessing when two different ids claim the same identity, or when nothing matches. It never falls back to an arbitrary theme in the listing, and no id is hard-coded in the workflow or the script. If the listing request itself fails, the job continues to the resolver, which still succeeds when the import response alone identifies the theme.

Run the same resolution locally against saved responses:

```bash
python scripts/theme/easystore_publish.py resolve \
  --import-response easystore-import.json \
  --themes-response easystore-themes.json \
  --display-name "CC main r451 abc1234" \
  --version "2.0.0+gh.451.abc1234"
```

## Publish request

The publish step repeats the observed browser request:

```text
PUT https://api.easystore.co/admin/v2/store/themes/<resolved theme id>
Content-Type: application/json

{}
```

It sends the same authorization and EasyStore infrastructure headers as the import, with a fresh `idempotency-key`. A non-2xx response fails the job and prints the response body.

After the publish request the job re-reads the theme listing (up to five attempts, five seconds apart, since the listing can lag) and records the state EasyStore reports for that theme, such as `role` and `published_at`, in the job summary. The job fails unless that state says the theme is live (`role: main`, or `published: true` when no role is reported). A 2xx publish status only proves EasyStore accepted the request.

## Troubleshooting

### Import did not run

The deploy job runs on every branch (`prod` environment for `main`, `dev` for the rest), but only when theme sources or their tooling changed - see the `paths` filter in the workflow. A push that only touches other files packages nothing and deploys nothing.

If the deploy job ran and failed on the credential check, `EASYSTORE_ADMIN_TOKEN`, `EASYSTORE_POD_ID` or `EASYSTORE_STORE_DOMAIN` is missing from the selected GitHub environment. Add it under **Settings → Environments**, then re-run the failed jobs.

### 401 or 403

The admin bearer token has likely expired, been revoked, or does not have access to the store. Obtain a fresh token from an authenticated EasyStore admin session and replace `EASYSTORE_ADMIN_TOKEN`.

### 400 or 422

Check the response body in the failed workflow step. Also run locally:

```bash
python scripts/theme/theme_ci.py check theme
python scripts/theme/theme_ci.py package theme cc-ez-theme.zip
python -c "from scripts.theme.theme_ci import validate_archive; print(validate_archive('cc-ez-theme.zip'))"
```

The archive validation command should print `[]`.

### Publish was not verified

The publish request returned 2xx but the verification step failed, so EasyStore does not report the imported theme as live. Read "EasyStore theme state after publishing" in the job summary for the `role` and `published` values EasyStore returned, and check **Channels → Online Store → Themes** in the store the environment points at.

### The theme id could not be resolved

The resolve step prints the expected theme name and version plus the themes EasyStore returned, then fails before anything is published. This is the safe outcome: no theme is published unless it can be identified.

Common causes:

- the theme listing request failed and the import response carried no theme id, so nothing identified the import;
- EasyStore renamed or truncated the theme card title, so no name matched. Check the printed candidate list against the expected name;
- an earlier run with the same run number and commit left a duplicate theme, so two ids claim one identity. Delete the stale theme in EasyStore and rerun.

The job summary and the failed step name the theme id it would have used, so the theme can also be published by hand in EasyStore.

### Publish returns 404

The resolved theme no longer exists, usually because it was deleted in EasyStore between import and publish. Rerun the workflow to import a fresh copy.

### Wrong store or infrastructure headers

Confirm the current EasyStore request headers in browser developer tools. If the pod ID or default domain has changed, update the `EASYSTORE_POD_ID` or `EASYSTORE_STORE_DOMAIN` repository variable rather than editing the workflow.

## Credential rotation

Because the bearer credential comes from an admin session, plan for periodic replacement. A failed deploy with `401` or `403` is a strong signal to capture a fresh token and update the GitHub secret.
