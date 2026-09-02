# Security policy

## Supported version

The actively supported production version is the code currently deployed from the repository's `main` branch and the immediately preceding known-good production revision used for rollback. Older historical revisions are not maintained as separate supported releases.

## Reporting a vulnerability

Do **not** report suspected vulnerabilities, exposed credentials, customer-data leaks, or exploitable production behavior in a public GitHub issue or discussion.

Use GitHub's private vulnerability reporting / Security Advisory flow for this repository when it is available. If that private channel is not enabled, contact the repository maintainer through an established private channel and include the repository name plus a short description of the issue. Do not include secrets in an initial message unless the channel is confirmed private.

A useful report includes:

- affected component and path;
- impact and realistic attack scenario;
- reproduction steps using non-sensitive test data;
- whether the issue is currently exploitable in production;
- any evidence that a token, session, customer record, or third-party credential was exposed;
- a suggested mitigation, if known.

## Credential exposure

Treat committed or logged credentials as compromised even if the commit is later reverted or rewritten.

If a credential may have been exposed:

1. Revoke or rotate it at the issuing service first.
2. Disable the affected automation or integration if continued execution could increase impact.
3. Preserve enough audit evidence to understand what ran and when.
4. Remove the secret from repository content, logs, artifacts, examples, and documentation where possible.
5. Verify replacement credentials use the minimum permissions required.
6. Re-run the affected integration only after the rotation and code/configuration review are complete.

Do not rely on deleting a Git commit as the only remediation.

## Sensitive data rules

Never commit or paste the following into repository content, issues, pull requests, Actions logs, test fixtures, or documentation examples:

- EasyStore admin bearer tokens or authenticated session material;
- Cloudflare API tokens, account credentials, or Worker secrets;
- HubSpot private-app tokens or customer exports;
- Slack webhook/signing secrets or private message payloads;
- customer personal data, order exports, addresses, phone numbers, or private identifiers;
- browser cookies, captured authorization headers, or private webhook payloads.

Use synthetic data in tests and redact screenshots/logs before attaching them to GitHub.

## Production security expectations

- Store credentials in GitHub Actions secrets or the target platform's secret store, not in tracked files.
- Prefer least-privilege tokens and narrowly scoped service accounts.
- Keep production publishing gated by successful validation and explicit repository workflow behavior.
- Do not bypass native EasyStore authorization or commerce behavior with fragile client-side interception.
- Treat third-party app hooks, checkout behavior, attribution, CRM synchronization, and Worker bindings as security-sensitive integration boundaries.
- Review dependency and workflow changes with the same care as runtime code because they can alter build or deployment trust.

## Incident response

For a production incident involving security or sensitive data, follow `docs/OPERATIONS_RUNBOOK.md` in addition to rotating credentials and disabling the affected path. Favor containment first, then evidence preservation, then root-cause remediation.