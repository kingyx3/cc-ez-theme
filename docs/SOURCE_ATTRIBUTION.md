# Source attribution

Which channel produced a customer, answered end to end.

Four systems are involved and none of them can answer it alone. Cloudflare knows
a click happened and where it came from. The storefront knows a browser. EasyStore
owns customer identity. HubSpot is where the answer has to land. This document is
the seam between them.

```text
Carousell listing / Facebook post / QR code
        │
        ▼
cardboard.sg/go/ca            Cloudflare Worker  (cc-attribution)
        │                     writes one D1 row: click_id + channel
        │                     redirects with ?cb_click_id= and a cookie
        ▼
storefront landing page       theme/snippets/attribution-click-id.liquid
        │                     stores the click id, cookie + localStorage
        ▼
account sign-up               theme/snippets/attribution-click-id-field.liquid
        │                     fills the hidden "Click ID" customer attribute
        │
        ▼
EasyStore customer record     the click id is now a fact EasyStore owns
        │
        ▼
HubSpot contact               Contact sync -> easystore_attr_click_id
        │
        ▼
HubSpot contact               scripts/cloudflare_hubspot_attribution.py
                              resolves the id in D1 and writes cc_acquisition_*
```

## What each layer is allowed to claim

**Layer 1 - clicks.** `cloudflare/attribution-worker` counts entries by channel
and campaign. It holds no email, mobile number, IP address, EasyStore customer id
or HubSpot contact id, and it never will. See its own README.

**Layer 2 - acquisition.** The chain above. It says: *this account was created by
a browser that had arrived through this click*. That is a genuine, deterministic
claim, and it is the only person-level claim this setup makes.

**Layer 3 - revenue.** Not built. Order-level attribution still has to come from a
deterministic EasyStore signal, as the Worker's README says. `cc_acquisition_*` on
a contact plus that contact's HubSpot Orders gets close enough for most reporting,
and is honest about being a join rather than a measurement.

## Why the click id, and not something simpler

The click id is minted server-side by the Worker and is a random UUID, so a
visitor cannot forge one that resolves: a value that is not in D1 joins to nothing
and is counted as unresolved. This is the opposite of a browser posting a
`customer_id`, which the Worker's README rightly refuses - there, a tampered value
would attach a real customer to the wrong data. Here the worst a tampered value
can do is attribute one sign-up to a click that a different browser made.

The direction matters more than the mechanism: **the untrusted side supplies the
opaque token, and the trusted side owns identity.**

## Setting it up

Only one step is manual, and it must be done in EasyStore admin before anything
joins.

**Deploy the theme first.** EasyStore renders every customer attribute as a
visible input on four pages - `register`, `activate_account`, `account` and
`details` - so an attribute created before the theme ships is a text box labelled
"Click ID" that shoppers are asked to fill in. The snippet is what hides it.

1. **Deploy the theme.** Both snippets ship with it and are already wired up.

2. **Create the customer attribute.** EasyStore admin → Settings → Customers →
   customer attributes. Add a **text** attribute titled exactly **`Click ID`**,
   and **do not mark it required**.

   - *Text, not dropdown.* The theme fills the input's value; a `<select>` would
     need a matching option to accept one.
   - *Not required.* The theme removes the browser-side `required` flag, but
     EasyStore may still enforce it server-side, and a shopper arriving organically
     has no click id to fill - a required field would block their sign-up.

   The theme matches the title case-insensitively against `Click ID`, `ClickID`,
   `cb_click_id`, `Source click ID` and `Attribution click ID`. Any of those work;
   the first is the one to use.

   The field is hidden from shoppers but stays fully visible in EasyStore admin,
   which is the point: the customer record gains a Click ID. It is hidden by id,
   so renaming or deleting the attribute gives the ordinary field back rather than
   breaking a form.

3. **Deploy the Worker**, which happens automatically when
   `cloudflare/attribution-worker/**` reaches `main`. This applies migration
   `0002`, which adds the automated-click columns.

4. **Confirm the repository secrets and the HubSpot scopes.** The join stage
   reads `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN` - the same two the
   Worker deployment uses - plus the `HUBSPOT_ACCESS_TOKEN` the CRM sync already
   has. The join only ever reads D1, so a dedicated token with D1 read on the one
   account is enough if you would rather not give the CRM workflow the deployment
   token.

   With no Cloudflare credentials configured, the CRM sync logs a notice and
   skips this stage entirely.

   The HubSpot token needs **`crm.schemas.contacts.read` and
   `crm.schemas.contacts.write`**. Those are optional for every other stage,
   which degrades to standard properties without them; this one cannot, because
   every property it writes is one it provisions. It fails rather than degrading,
   and because it runs last, a failure costs nothing else in the run.

5. **Wait for a real sign-up through a tracked link, then run the sync.** Until
   then the stage reports `contacts_with_click_id: 0` and provisions nothing.

### Verifying it

```bash
# 1. A tracked click hands back a click id and a cookie.
curl -sSD - -o /dev/null "https://cardboard.sg/go/fb?campaign=test"
#    Look for: Location: ...&cb_click_id=<uuid>
#              Set-Cookie: cb_click_id=<uuid>; Domain=cardboard.sg; ...

# 2. It reached D1.
npx wrangler d1 execute cc-attribution --remote \
  --command "SELECT click_id, source, campaign, bot, bot_reason
             FROM source_clicks ORDER BY clicked_at DESC LIMIT 5;"

# 3. Register an account in that browser, then run the Contact sync and the join.
python scripts/easystore_hubspot_customer_sync.py
python scripts/cloudflare_hubspot_attribution.py
```

The contact should now carry `cc_acquisition_source`, and the join summary should
report `contacts_updated: 1`.

## What HubSpot ends up holding

Provisioned on first use in a **Cloudflare Attribution** property group, kept
separate from `EasyStore Sync` so a CRM user can tell which system reported a
value:

| HubSpot Contact property | Holds |
| --- | --- |
| `cc_acquisition_click_id` | the click the account was created under |
| `cc_acquisition_source` | `carousell`, `facebook`, `whatsapp`, `qr` |
| `cc_acquisition_medium` | `marketplace`, `social`, `messaging`, `offline` |
| `cc_acquisition_campaign` | the campaign label on the link |
| `cc_acquisition_entry_path` | the `/go/*` URL used |
| `cc_acquisition_country` | the country Cloudflare reported for the click |
| `cc_acquisition_at` | when the click happened |
| `cc_acquisition_automated` | why the click looked automated, or blank |

HubSpot's own `hs_analytics_source` family is deliberately untouched. Those belong
to HubSpot's tracking code, are enumerated against HubSpot's channel list, and are
not this integration's to define.

## The rules this stage will not break

- **An acquisition is written once.** A contact already carrying a different
  `cc_acquisition_click_id` is reported as `contacts_with_conflicting_click_id`
  and left alone. How an account was acquired is a fact about a moment that has
  passed; a later click cannot change it.
- **A click id with no D1 row writes nothing**, and is counted as
  `click_ids_not_found_in_d1`. The commonest cause is a click older than the
  data, not a bug.
- **A stored value that is not a UUID never reaches a query.** The attribute is
  filled by a script in a browser, so the value is treated as untrusted input and
  counted as `contacts_with_unusable_click_id`.
- **A rerun writes nothing new.** `contacts_already_attributed` is the normal
  headline number of a healthy scheduled run.

## Limits, stated plainly

- **Registered accounts only.** A guest checkout never fills a customer
  attribute, so it is never attributed. This is the main gap, and closing it
  needs order-level attribution (Layer 3).
- **Customers who signed up before this shipped are never attributed.** There is
  no click id to find. `contacts_with_click_id` will stay well below the contact
  count for a long time, and that is correct.
- **Last touch before sign-up, not first ever touch.** The cookie is refreshed by
  each new tracked click; the attribute is filled once, at registration, from
  whatever the cookie held then. So the value is the click that was current when
  the account was created.
- **One browser, one attribution.** Two people signing up on a shared device
  share a click id. Reported as `click_ids_shared_by_multiple_contacts`.
- **A cleared browser loses the link.** Cookie and `localStorage` both go; the
  sign-up is then simply unattributed rather than wrongly attributed.
- **Hiding the field is the theme's job.** A shopper on a browser with neither
  `:has()` support nor JavaScript would see the input. That is a very narrow
  combination, but it is the reason the attribute must never be required.
- **One storefront domain.** The cookie is set for `cardboard.sg` and its
  subdomains, derived from the Worker's `STORE_URL`. A shopper who reaches the
  store on a different host - the raw `*.easy.co` domain, say - never sees it, and
  registering there is unattributed. Set the Worker's `COOKIE_DOMAIN` var if the
  storefront ever moves.
- **Only `/go/*` entries exist as clicks.** Organic, direct and search traffic
  produce no click row, so this measures the tracked channels against each other
  and never against the whole funnel.
- **`cc_acquisition_automated` is a caution, not a verdict.** A shopper's browser
  may prefetch a link before they tap it, which is a real visit behind an
  automated-looking request. The flag makes such a click reviewable rather than
  quietly trusted.

## Channel reporting from D1

Automated clicks are recorded rather than dropped, so every count needs to say
whether it includes them.

```sql
-- Real clicks by channel.
SELECT source, COUNT(*) AS clicks
FROM source_clicks
WHERE bot = 0
GROUP BY source
ORDER BY clicks DESC;

-- How much of the raw total was link previews and prefetches.
SELECT source, bot_reason, COUNT(*) AS requests
FROM source_clicks
WHERE bot = 1
GROUP BY source, bot_reason
ORDER BY requests DESC;

-- Campaign performance, real clicks only.
SELECT source, campaign, COUNT(*) AS clicks
FROM source_clicks
WHERE bot = 0
GROUP BY source, campaign
ORDER BY clicks DESC;
```

## Why the theme side is two snippets

Capturing the click id and filling the customer attribute look like one job, and
putting them in one snippet in the layout head **took the storefront down** the
first time this shipped.

`shop.attribute_settings` is populated on the four customer pages that ask for
it. Looping it from the layout head meant every page in the store - the homepage
included - resolved a shop object it had never touched before, and EasyStore
errored rather than rendering. CI could not catch it: the packaging workflow
validates Liquid structurally and the browser suite drives the *published*
storefront, so nothing executed the new Liquid until it was live.

So the two halves live where each one belongs:

| Snippet | Included from | Reads |
| --- | --- | --- |
| `attribution-click-id` | the layout head, every page | nothing but the browser - no `shop`, no `customer`, no `settings` |
| `attribution-click-id-field` | the four customer templates | `shop.attribute_settings`, on pages that already loop it |

`tests/test_source_attribution_capture.py` keeps that split: it asserts the head
snippet contains no Liquid logic whatsoever, and that no template outside those
four reads `shop.attribute_settings`.

The lesson generalises past this feature. **A snippet in the layout head runs on
every page, so anything it reads is now read by every page** - the cost and the
blast radius of a Liquid object are decided by where you include it, not by what
it does.

The field snippet also sticks to constructs the rest of the theme already proves
work on EasyStore's Liquid: the `default: '' | append: '' | downcase | strip`
coercion used by `customer-order-limit-rule`, and plain `==` comparisons rather
than testing an array with `contains`, which nothing else in this theme does.

## Where each part lives

| Part | File |
| --- | --- |
| Click capture and redirect | `cloudflare/attribution-worker/src/index.js` |
| Click storage | `cloudflare/attribution-worker/migrations/` |
| Worker behaviour tests | `cloudflare/attribution-worker/test/worker.test.js` |
| Storefront capture | `theme/snippets/attribution-click-id.liquid` |
| Attribute fill and hide | `theme/snippets/attribution-click-id-field.liquid` |
| Storefront wiring tests | `tests/test_source_attribution_capture.py` |
| Attribute → HubSpot | `scripts/easystore_hubspot_sync.py` (customer attributes) |
| The join | `scripts/cloudflare_hubspot_attribution.py` |
| Join tests | `crm_tests/test_cloudflare_attribution.py` |
| Schedule | `.github/workflows/sync-easystore-customers-hubspot.yml` |
