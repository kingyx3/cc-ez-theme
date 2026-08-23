# Attribution runtime constraints

This file records production facts that change how gaps in the generic attribution design should be interpreted for Cardboard Collective.

## Checkout requires a registered account

The production storefront UI does **not** allow guest checkout. A shopper must sign in or register before completing a purchase.

Treat this as an operating invariant for attribution and CRM work:

- do not design or report a separate guest-order attribution path while this UI rule remains in force;
- every storefront order is expected to belong to an EasyStore customer;
- `easystore_customer_id` is therefore the preferred Order → HubSpot Contact association key, with normalized phone retained only as a fallback/legacy association;
- the Order sync reports missing, unmatched, or ambiguous customer IDs so a future checkout/configuration change cannot silently reintroduce a guest-order gap.

If EasyStore checkout settings or the theme later permit guest purchase, revisit this document and `docs/SOURCE_ATTRIBUTION.md` before claiming complete revenue attribution.

## Two complementary attribution paths

### Deterministic acquisition: Cloudflare click ID

`cc-attribution` mints `cb_click_id`, records the channel/campaign in D1, and the theme persists that opaque ID into the registered EasyStore customer. The HubSpot attribution job resolves the ID and writes `cc_acquisition_*` onto the Contact.

That remains the deterministic acquisition answer for links served by `cc-attribution`.

### Browser/session attribution: HubSpot tracking code

The EasyStore theme loads the HubSpot tracking code for portal `246919056` on every storefront page. This is what allows HubSpot to see landing-page UTMs and browser sessions from deployment day forward. It is not retroactive: traffic before the code was installed cannot be reconstructed by HubSpot browser analytics.

HubSpot's own analytics properties remain separate from `cc_acquisition_*`; neither should overwrite the other.

## Clare's Reality Fracture links

The temporary `cc-rf` Worker serves `go.cardboard.sg` without changing the EasyStore apex/www DNS records.

Current canonical UTMs:

- `utm_source=facebook`
- `utm_campaign=rf`
- `utm_content=grp-aug26` for `/rf`
- `utm_content=grp-bump-aug26` for `/rf-bump`

These links are useful immediately for HubSpot browser/session attribution once the tracking code is deployed. They do **not** currently mint the repo's `cb_click_id` or write a row to the `cc-attribution` D1 database, so they should not be described as feeding `cc_acquisition_*` until the slugs are folded into the deterministic Worker (or `cc-rf` is changed to emit the same click-ID/D1 contract).

## Cloudflare routing constraint

The repo config attaches `cc-attribution` to the zone route `cardboard.sg/go/*`. A zone route only receives requests that actually pass through Cloudflare's proxy. If the apex/www DNS records are DNS-only, requests go directly to EasyStore and Worker invocations remain zero even though the Worker and route are deployed correctly.

A dedicated proxied/custom-domain hostname such as `go.cardboard.sg` avoids changing the store's apex/www traffic path. When consolidating `cc-rf` later, preserve the live `/rf` and `/rf-bump` URLs and the UTM canon above.
