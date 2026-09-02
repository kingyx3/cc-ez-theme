# Support and issue reporting

Use GitHub issues for repository defects, documentation gaps, reproducible storefront regressions, and maintainable feature requests that can be discussed publicly.

## Before opening an issue

- Check the root `README.md` and `docs/README.md` for the relevant subsystem document.
- Confirm the problem still occurs on the current code or deployed production version.
- For theme/package issues, run the validator and relevant tests when possible.
- Remove customer data, credentials, session material, private webhook payloads, and sensitive production logs from any evidence.

## Useful bug report information

Include:

- affected component or storefront surface;
- expected behavior and actual behavior;
- reproducible steps;
- browser/device for storefront issues;
- commit, workflow run, preview theme, or deployment identifier when known;
- sanitized logs/screenshots;
- whether production customers are currently affected;
- a workaround, rollback, or containment action already taken.

## Production incidents

For an active production incident, restore or disable the affected path first using `docs/OPERATIONS_RUNBOOK.md`. An issue can be used afterward to track root cause and follow-up work, but it should not delay containment or rollback.

## Security and sensitive data

Do not use public issues for vulnerabilities, exposed credentials, customer-data leaks, or exploitable production behavior. Follow `SECURITY.md`.

## Feature requests

Describe the customer/maintainer problem, the desired outcome, affected EasyStore or integration surfaces, and any compatibility constraints. Avoid prescribing fragile client-side interception when the requirement belongs in EasyStore or another server-side enforcement layer.