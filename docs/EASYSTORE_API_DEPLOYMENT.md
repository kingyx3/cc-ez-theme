# EasyStore API Deployment

The `Package EasyStore theme` GitHub Actions workflow automatically imports a theme into EasyStore after validation and packaging complete successfully on `main`. Pushes to any other branch stop after the ZIP is built.

The import uses the same EasyStore admin endpoint observed in the browser UI:

```text
POST https://api.easystore.co/admin/v2/store/themes/assets/import
```

The imported theme is not intentionally published. Treat every automated import as an unpublished preview candidate until it has been reviewed in EasyStore.

## Workflow order

For every push branch, and for a manual workflow dispatch, the workflow runs these jobs in order:

1. `test` validates the real `theme/` source and enforces the existing test coverage requirement;
2. `package` creates and validates the normal downloadable `cc-ez-theme` artifact;
3. `deploy` runs only after `package` succeeds, and only when the run's ref is `refs/heads/main`, and imports a deployment-specific ZIP into EasyStore.

On every other branch the workflow ends at step 2. The ZIP artifact is still produced for download and manual upload, but nothing is sent to EasyStore. A manual `workflow_dispatch` follows the same rule: it imports only when dispatched against `main`.

The deploy job does not replace the normal package artifact. The artifact remains available as a manual fallback.

If `EASYSTORE_ADMIN_TOKEN` is not configured, validation and packaging still succeed. The deploy job prints a warning and skips the EasyStore request. Once the secret is configured, subsequent successful `main` runs import automatically.

The chained path has been verified against EasyStore with a successful HTTP 200 import from the PR branch.

## Deployment naming

The source theme remains unchanged in Git. Before deployment, the workflow copies `theme/` to a temporary staging directory and stamps deployment metadata into both:

```text
config/settings_schema.json
editor_config/settings_schema.json
```

Only the staging copy is changed. The workflow updates `theme`, `theme_name` when present, and `theme_version`, then validates and packages that staging copy.

The upload ZIP filename also carries the same Git identity while preserving the required internal `cc-ez-theme/` archive root.

Because the deploy job is gated to `main`, the automatic import always produces the `main` identity below. The branch and release naming rules are retained so the same identity scheme still applies if the gate is ever widened, and so the naming is unambiguous when a non-`main` package artifact is uploaded manually.

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

The workflow defaults to the values observed for this store:

```text
EASYSTORE_POD_ID=1007
EASYSTORE_STORE_DOMAIN=cardboardcollective.easy.co
```

To override them, create repository Actions variables with those names under **Settings → Secrets and variables → Actions → Variables**.

The API URL is intentionally fixed in the workflow so a secret or variable cannot silently redirect the upload to another host.

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

## Troubleshooting

### Import was skipped

First check the branch. The deploy job only runs on `main`, so a run on any other branch shows the job as skipped and ends after the packaging step. This is expected; download the `cc-ez-theme` artifact and upload it manually if a preview is needed.

On a `main` run, check the deploy job for the warning that `EASYSTORE_ADMIN_TOKEN` is not configured. Add the repository secret and rerun the workflow or push another commit.

### 401 or 403

The admin bearer token has likely expired, been revoked, or does not have access to the store. Obtain a fresh token from an authenticated EasyStore admin session and replace `EASYSTORE_ADMIN_TOKEN`.

### 400 or 422

Check the response body in the failed workflow step. Also run locally:

```bash
python scripts/theme_ci.py check theme
python scripts/theme_ci.py package theme cc-ez-theme.zip
python -c "from scripts.theme_ci import validate_archive; print(validate_archive('cc-ez-theme.zip'))"
```

The archive validation command should print `[]`.

### Wrong store or infrastructure headers

Confirm the current EasyStore request headers in browser developer tools. If the pod ID or default domain has changed, update the `EASYSTORE_POD_ID` or `EASYSTORE_STORE_DOMAIN` repository variable rather than editing the workflow.

## Credential rotation

Because the bearer credential comes from an admin session, plan for periodic replacement. A failed deploy with `401` or `403` is a strong signal to capture a fresh token and update the GitHub secret.
