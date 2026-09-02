# Documentation index

This directory is the maintainer knowledge base for the Cardboard Collective EasyStore theme and the production integrations that live in the same repository.

## Start here

| Goal | Document |
| --- | --- |
| Understand the theme architecture and editing conventions | [THEME_GUIDE.md](THEME_GUIDE.md) |
| Review production safety requirements before shared commerce changes | [THEME_PRODUCTION_SAFETY.md](THEME_PRODUCTION_SAFETY.md) |
| Release, preview, rollback, or respond to an incident | [OPERATIONS_RUNBOOK.md](OPERATIONS_RUNBOOK.md) |
| Validate and package the theme | [PACKAGING_AND_DEPLOYMENT.md](PACKAGING_AND_DEPLOYMENT.md) |
| Understand automatic EasyStore import/publish behavior | [EASYSTORE_API_DEPLOYMENT.md](EASYSTORE_API_DEPLOYMENT.md) |
| Operate the EasyStore-to-HubSpot customer sync | [CUSTOMER_CRM_SYNC.md](CUSTOMER_CRM_SYNC.md) |

## Storefront and customer experience

- [THEME_GUIDE.md](THEME_GUIDE.md) — architecture, customization, navigation, product organization, and maintenance.
- [THEME_PRODUCTION_SAFETY.md](THEME_PRODUCTION_SAFETY.md) — mandatory invariants and review matrix for production-sensitive theme work.
- [CUSTOMER_SIGNUP_FLOW.md](CUSTOMER_SIGNUP_FLOW.md) — customer registration behavior and related integration assumptions.
- [CUSTOMER_ORDER_LIMITS.md](CUSTOMER_ORDER_LIMITS.md) — historical/architectural context for order-limit behavior and constraints.
- [CUSTOMER_PURCHASE_LIMITS.md](CUSTOMER_PURCHASE_LIMITS.md) — purchase-limit behavior and implementation notes.
- [EASYSTORE_CHECKOUT_CART_SYNC.md](EASYSTORE_CHECKOUT_CART_SYNC.md) — checkout/cart synchronization behavior.

## Deployment and operations

- [OPERATIONS_RUNBOOK.md](OPERATIONS_RUNBOOK.md) — release readiness, preview, deployment, rollback, and incident response.
- [PACKAGING_AND_DEPLOYMENT.md](PACKAGING_AND_DEPLOYMENT.md) — deterministic ZIP generation, artifact structure, CI behavior, and release acceptance.
- [EASYSTORE_API_DEPLOYMENT.md](EASYSTORE_API_DEPLOYMENT.md) — EasyStore admin token, imported-theme identity resolution, publish behavior, and troubleshooting.

Worker-specific deployment and runtime notes live with the worker code:

- `cloudflare/attribution-worker/README.md`
- `cloudflare/easystore-slack-worker/README.md`

## CRM and attribution

- [CUSTOMER_CRM_SYNC.md](CUSTOMER_CRM_SYNC.md) — EasyStore customer synchronization into HubSpot.
- [CRM_FIELD_MAPPING.md](CRM_FIELD_MAPPING.md) — source-to-CRM field mapping.
- [MARKETING_LINKS.md](MARKETING_LINKS.md) — tracked campaign-link construction.
- [SOURCE_ATTRIBUTION.md](SOURCE_ATTRIBUTION.md) — customer/source attribution model.
- [ORDER_SOURCE_ATTRIBUTION.md](ORDER_SOURCE_ATTRIBUTION.md) — per-order attribution and production smoke tests.

## Documentation maintenance rules

Documentation is part of the production change. Update it in the same pull request when a change modifies any of the following:

- required local dependencies or commands;
- repository layout or ownership boundaries;
- configuration, environment variables, GitHub secrets, or repository variables;
- workflow triggers, release gates, deployment behavior, or rollback steps;
- production URLs, integration endpoints, data ownership, or retention assumptions;
- supported storefront behavior or known operational constraints.

Prefer one authoritative document for each procedure and link to it rather than copying long instructions into multiple files. When an old procedure is no longer safe, remove or clearly mark it as historical so maintainers cannot mistake it for the current runbook.

Never place real secrets, bearer tokens, customer data, session cookies, private webhook payloads, or production exports in documentation examples.