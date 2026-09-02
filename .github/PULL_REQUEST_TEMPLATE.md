## Summary

<!-- What changed and why? -->

## Production impact

<!-- Which storefront surfaces, workflows, workers, CRM/attribution paths, or external integrations can be affected? -->

- [ ] Theme/storefront
- [ ] EasyStore deployment
- [ ] Cloudflare Worker
- [ ] CRM / HubSpot sync
- [ ] Attribution / marketing tracking
- [ ] CI / repository tooling only
- [ ] Documentation only

## Validation

<!-- List commands/workflows run and their results. -->

- [ ] Relevant unit/validator checks pass
- [ ] Relevant CI workflow passes
- [ ] Package artifact validated, if this changes the theme/package tooling
- [ ] Relevant Playwright checks pass, if storefront-visible

## Preview / manual verification

<!-- For production-sensitive theme work, identify the unpublished preview and what was tested. Use N/A only when genuinely not applicable. -->

## Configuration and migrations

<!-- New/changed secrets, repository variables, Worker bindings, schedules, migrations, external scopes, or manual platform configuration. Never include secret values. -->

## Rollback

<!-- Identify the known-good version/commit/theme or the concrete disable/revert procedure. -->

## Documentation

- [ ] Documentation is unchanged because behavior/operations are unchanged
- [ ] Documentation was updated in this PR

## Release acknowledgement

- [ ] I reviewed `docs/THEME_PRODUCTION_SAFETY.md` for production-sensitive theme changes
- [ ] I understand that a successful theme workflow on `main` can publish to the live EasyStore storefront when deployment credentials and publishing are enabled
