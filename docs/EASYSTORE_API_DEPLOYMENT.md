# EasyStore API Deployment

This repository includes a manual GitHub Actions workflow that validates, packages, and imports the theme through the same EasyStore admin API endpoint used by the browser UI.

## What the workflow does

The `Deploy EasyStore theme` workflow:

1. validates the theme;
2. runs the test suite with the existing coverage requirement;
3. builds `cc-ez-theme.zip` with `scripts/theme_ci.py`;
4. validates the generated archive;
5. sends the ZIP as multipart field `file` to:

```text
POST https://api.easystore.co/admin/v2/store/themes/assets/import
```

The workflow is `workflow_dispatch` only. A normal push does not import a theme into EasyStore.

The import creates/imports a theme but does not intentionally publish it. Preview the imported theme in EasyStore before publishing.

## Required GitHub secret

Create this repository Actions secret:

```text
EASYSTORE_ADMIN_TOKEN
```

Store only the token value, without the leading `Bearer ` text. The workflow adds the `Bearer` authorization scheme when sending the request.

Never commit this credential, paste it into an issue or pull request, or print it in workflow output.

## Getting the EasyStore admin bearer token

EasyStore's admin UI uses a bearer credential for authenticated API requests. This is an admin session credential rather than a permanent project API key, so it can expire and may need to be refreshed.

To obtain the credential from your own EasyStore admin session:

1. Sign in at `https://admin.easystore.co/` in your normal browser.
2. Open the browser developer tools (`F12` or `Ctrl+Shift+I`).
3. Open the **Network** panel.
4. Perform an authenticated admin action. The most direct option is to open the theme uploader and perform a theme import.
5. Select a request to `api.easystore.co`. For the theme uploader, look for `/admin/v2/store/themes/assets/import`.
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

## Optional repository variables

The workflow currently defaults to the values observed for this store:

```text
EASYSTORE_POD_ID=1007
EASYSTORE_STORE_DOMAIN=cardboardcollective.easy.co
```

To override them, create repository Actions variables with those names under **Settings → Secrets and variables → Actions → Variables**.

The API URL is intentionally fixed in the workflow so a secret or variable cannot silently redirect the upload to another host.

## Running a deployment

1. Open **Actions** in GitHub.
2. Select **Deploy EasyStore theme**.
3. Choose **Run workflow**.
4. Select the branch or commit you want to import.
5. Run the workflow.
6. Confirm the final step reports a 2xx HTTP status.
7. In EasyStore, open **Channels → Online Store → Themes**.
8. Find the newly imported theme and preview it before publishing.

The workflow creates a fresh idempotency key for each import and sends the captured EasyStore admin headers required by the current integration.

## Troubleshooting

### 401 or 403

The admin bearer token has likely expired, been revoked, or does not have access to the store. Obtain a fresh token from an authenticated EasyStore admin session and replace `EASYSTORE_ADMIN_TOKEN`.

### 400 or 422

Check the response body in the failed workflow step. Also run:

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
