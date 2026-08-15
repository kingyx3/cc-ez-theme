# Theme Guide

## 1. Purpose

This repository contains the Cardboard Collective storefront theme for
EasyStore. The theme is designed around four goals:

1. Put commercially important collections near the top of the homepage.
2. Make long trading-card product names readable on desktop and mobile.
3. Keep navigation, product data, and merchandising editable through
   EasyStore wherever the platform supports it.
4. Produce a deterministic upload archive that EasyStore can import.

The theme is presentation code. Products, inventory, customers, orders,
collections, navigation records, and installed apps remain managed
by EasyStore.

## 2. What is packaged

The upload builder reads `theme/` but does not copy every file found there. It
ships only supported runtime files from these eight directories:

| Directory | Responsibility | Packaged file types |
|---|---|---|
| `assets/` | Storefront CSS and JavaScript | All runtime asset files |
| `config/` | Published theme settings | JSON |
| `editor_assets/` | Theme-editor copies of storefront assets | All runtime asset files |
| `editor_config/` | Theme-editor settings | JSON |
| `layout/` | Shared HTML document shell | Liquid |
| `sections/` | Configurable page components | Liquid |
| `snippets/` | Reusable rendering fragments | Liquid |
| `templates/` | Route-level templates | Liquid |

The following are intentionally outside `theme/` and never enter the upload
archive:

- `README.md`
- `docs/`
- `.github/`
- `scripts/`
- `tests/`
- coverage output
- local build output
- Git metadata

See [Packaging and deployment](PACKAGING_AND_DEPLOYMENT.md) for the complete
archive contract.

## 3. Rendering architecture

```text
EasyStore data and settings
          |
          v
layout/theme.liquid
          |
          v
route template
          |
          v
configurable sections
          |
          v
reusable snippets
          |
          v
assets + editor_assets
```

### Layout

`layout/theme.liquid` defines the shared page document, loads global assets,
renders EasyStore content hooks, and injects the route content.

The conversion-focused visual layer is loaded from
`assets/conversion-theme.css`. It is deliberately separate from the inherited
base styles so commercial refinements are easier to review and maintain.

### Templates

Templates map EasyStore routes to page-level rendering:

| Template | Route purpose |
|---|---|
| `home.liquid` | Homepage |
| `collection.liquid` | Collection listing |
| `product.liquid` | Product detail |
| `search.liquid` | Search results |
| `cart.liquid` | Cart |
| `list-collections.liquid` | Collection directory |
| `blog.liquid`, `article.liquid` | Editorial content |
| `store-locator.liquid` | Store locations |
| `customers/*` | Customer account routes |
| `404.liquid` | Not-found page |

The homepage template renders EasyStore's dynamic `content_for_index`. The
actual homepage section order is stored in the settings data rather than
hard-coded in `home.liquid`.

### Sections

Sections are configurable page components. Important sections include:

| Section | Purpose |
|---|---|
| `header.liquid` | Announcement, logo, desktop navigation, mobile menu, account/search/cart controls |
| `featured-collection.liquid` | Sales-focused product collection |
| `collection-list.liquid` | Tabbed collection display |
| `image-banner.liquid` | Campaign artwork and call to action |
| `main-product.liquid` | Product details and variants |
| `main-collection.liquid` | Collection grid, sorting, and filters |
| `main-cart.liquid` | Cart contents |
| `footer.liquid` | Social links, contact details, and policy links |

Each configurable section ends with an EasyStore schema block. Keep schema
JSON valid and include exactly one `{% schema %}` / `{% endschema %}` pair when
a schema is present.

### Snippets

Snippets are shared partials. Examples:

- `product-card.liquid` renders products on homepage and collection grids.
- `price.liquid` renders sale and regular prices.
- `search-modal.liquid` renders header search.
- `filters.liquid` and `collection-sorting.liquid` support collection browsing.
- `svg-definitions.liquid` centralizes interface icons.
- `translation-fallback.liquid` prints a platform translation, or a literal
  fallback when the store has none.
- `low-inventory-notice.liquid` prints the remaining stock when only a few units
  are left, and at every quantity for the configured series.

Use a snippet when the same rendering is needed in several sections or
templates. Use a section when merchants need editor-facing settings or blocks.

## 4. Storefront and editor asset parity

EasyStore maintains separate storefront and editor asset directories. Every
file under `theme/assets/` must have a counterpart with the same relative path
under `theme/editor_assets/`, and vice versa.

When changing a mirrored asset:

1. Edit the storefront file.
2. Apply the identical change to the editor copy.
3. Confirm the files match.
4. Run theme validation.

Example:

```bash
cmp -s \
  theme/assets/conversion-theme.css \
  theme/editor_assets/conversion-theme.css
```

The validator rejects missing counterparts because a storefront/editor mismatch
can make preview behavior differ from the published theme.

## 5. Homepage merchandising

Homepage order is controlled by `content_for_index` in:

- `theme/config/settings_data.json`
- `theme/editor_config/settings_data.json`

The default order is:

1. Best Sellers
2. The Hobbit Collection
3. Marvel Collection
4. Secrets of Strixhaven

### Best Sellers

- Section type: `featured-collection`
- Default title: `Best Sellers`
- Default collection: `feature-on-homepage`
- Default display: 6 products, 3 per desktop row
- Homepage quick add: disabled

### The Hobbit Collection

- Section type: `featured-collection`
- Default title: `The Hobbit Collection`
- Default collection: `the-hobbit`
- Default display: 6 products, 3 per desktop row
- Homepage quick add: disabled

### Marvel Collection

- Section type: `featured-collection`
- Default title: `Marvel Collection`
- Default collection: `marvel-super-heroes`
- Default display: 6 products, 3 per desktop row
- Homepage quick add: disabled

### Secrets of Strixhaven

- Section type: `featured-collection`
- Default title: `Secrets of Strixhaven`
- Default collection: `secrets-of-strixhaven`
- Default display: 6 products, 3 per desktop row
- Homepage quick add: disabled

### Editing the homepage in EasyStore

Use the theme customizer to:

- reorder sections;
- change collection assignments;
- edit eyebrow, title, and supporting text;
- change accent colors;
- adjust product count and desktop columns;
- enable or disable mobile swiping;
- add or remove optional campaign sections.

The section chooses which collection to render. Product membership and product
ordering remain collection responsibilities in EasyStore.

## 6. Product cards

`snippets/product-card.liquid` is the shared product-card renderer. It supports:

- primary and secondary product images;
- sale and sold-out badges;
- title and price;
- optional quick add outside homepage featured collections;
- variant thumbnails;
- a remaining-stock notice when five or fewer units are left;
- a view-details call to action.

Product titles are allowed to use the full card width and wrap safely. Variant
thumbnails belong below the primary information rather than competing with the
title for horizontal space.

Homepage featured collections use one section-level spacing margin only. The
conversion stylesheet keeps their heading gap, grid row gap, card padding, and
minimum information height compact on desktop and mobile; avoid adding a
second `spaced-section` class inside the section wrapper.

When changing card layout, test:

- a short title;
- a long title with punctuation;
- a long unbroken token;
- sale pricing;
- sold-out products;
- products with and without variant thumbnails;
- products with one, five, and six units left, and with untracked stock;
- two-column mobile grids;
- three-, four-, and five-column desktop grids.

Avoid single-line truncation for product titles unless a deliberate design
decision is documented. Trading-card product names commonly contain set,
language, configuration, and edition information that customers need before
opening the product.

## 7. Header and announcement

The header settings include:

- primary and alternate logos;
- logo alignment and size;
- sticky-header behavior;
- header colors;
- announcement visibility;
- announcement message, link, background, and text color.

The announcement hover and keyboard-focus state preserves the configured text
color. Do not reintroduce a generic link-hover color on the dark announcement
background.

### Navigation data

The desktop header and mobile drawer expose a Browse dropdown followed by five
top-level destinations in a fixed order:

1. Browse (EasyStore product collection hierarchy)
2. Crack-a-Pack (`/collections/late-night-crackers`)
3. Hobbit (`/collections/the-hobbit`)
4. Marvel (`/collections/marvel-super-heroes`)
5. Strixhaven (`/collections/secrets-of-strixhaven`)
6. About Us (`/pages/about-us`)

About Us is pushed to the right edge of the desktop navigation area. The
Browse reads `contents.catalog.links` and renders up to three collection levels
from EasyStore's product catalog hierarchy. On desktop, hovering or focusing a
parent collection opens its child collection flyout; mobile retains nested
drill-down navigation. The four fixed collection shortcuts remain direct
EasyStore links.

The theme controls:

- visual treatment;
- a single-row desktop layout with the logo directly before navigation;
- mobile drawer behavior;
- the Browse dropdown backed by EasyStore navigation records;
- the fixed collection shortcut destinations.

## 8. Product taxonomy

Recommended classification for sealed MTG products:

| Dimension | Recommended EasyStore model |
|---|---|
| Set or release | Primary collection |
| Major product type | Cross-set collection |
| Language | Variant or filter attribute |
| Edition/configuration | Variant or tag |
| Preorder/availability | Operational tag or product state |
| Best seller/new release | Curated collection |

A product can belong to both its set collection and its product-type
collection. Tags are useful for search, administration, reporting, and
filtering, but EasyStore does not directly expose tags as standard navigation
destinations.

Keep product-type collections for the few categories customers actively browse,
such as Collector Booster Boxes, Play Booster Boxes, Bundles, and Booster
Packs. Use tags for narrower operational detail.

## 9. Remaining stock and out-of-stock interest

`snippets/low-inventory-notice.liquid` prints "Only N left" once a product is
down to five or fewer units. Cards report the total across the variants a
shopper can buy; the product page, quick view, and the featured-product section
report the selected variant, and `assets/product-form.js` refreshes it when the
shopper picks another variant. Every surface that renders a `<product-form>`
renders the notice inside it, because the script refreshes it through its own
subtree. The featured-product section renders `featured_product` rather than
`product`, so it passes its product in as `low_inventory_product`.

The count is only printed when the platform reports a positive quantity. A
product whose stock is not tracked reports zero or nothing, which is
indistinguishable here from sold out, so no count is claimed for it. Sold-out
products keep their existing badge.

Which variants are counted is decided by the quantity, not by an availability
flag. A variant is dropped only when `available`, `is_available`, or
`is_enabled` reads false, and is counted when none of them is sent: a product
page renders the product EasyStore loads in full, where a variant carries
`available`, while cards render the product objects from a collection, whose
variants do not all carry that field — the card's own variant thumbnails read
`is_enabled`, and EasyStore names the same idea `is_available` on order line
items. Requiring `available` counted nothing for those variants, so cards on the
collection, home, search, and cart pages fell back to the product-level total
or printed nothing while the product page printed a count. The threshold lives in one place, the
`low_inventory_threshold` assignment in the snippet, and reaches the script
through `data-low-inventory-threshold`.

One series is exempt from the threshold and prints its count at every quantity,
so those products advertise their stock the whole way down rather than only in
their last five units. That series is Late Night Crackers, sold through
`/collections/late-night-crackers` and merchandised in the header as
Crack-a-Pack. Each episode is a livestream, so its products sell against a
scheduled stream rather than an on-demand release, and a live count is worth
more to a shopper watching it than a notice that appears only in the last five
units. It is configured by the other assignment in the same snippet:

```liquid
{% assign low_inventory_show_all_handle = 'late-night-crackers' %}
```

The value is matched anywhere in the product's handle, and case does not matter
on either side, so the one line covers `late-night-crackers-ep3`, episodes not
streamed yet, and `bundle-late-night-crackers-ep3`, which carries the series
name in the middle of its handle.

The handle is read from the product's link as well as from `product.handle`,
because a card is not given the same product object a product page is: a listing
serializes less of the product, and a card whose product arrived without a handle
read as a product outside the series and went back to the five-unit threshold —
which is how a series product printed its count on its own page and on none of
its cards. Every card links to its product, so the link always spells the handle
out. Only the segment after `/products/` is read, so a link written within a
collection (`/collections/late-night-crackers/products/mtg-hob-cbb-en`) is
matched on the product it points at, never on the collection it was written
through, and a link naming no product is ignored rather than matched whole. The
SKU is read as well, since this theme already identifies a product by either,
as the purchase limits do. Products whose handle does not contain it stay
on the five-unit threshold. Those products render `all` in place of the number in
`data-low-inventory-threshold`, which is how `assets/product-form.js` keeps
printing the count after a variant change. Leaving the value blank puts every
product back on the threshold.

Printing every count is not a licence to invent one: a product whose stock is
untracked or sold out still shows nothing, exactly as it does under the
threshold.

When a card and its product page disagree about a count, paste
`scripts/inventory-notice-probe.console.js` into the browser console on the page
showing the cards. For every product on it, the probe prints what the card
printed, what that product's own page prints, the quantities EasyStore reports
for it, and which of the two is at fault: an untracked product, a card that did
not recognise the series, or a card that counted no stock from the product
object it was given.

For out-of-stock products, a free manual alternative is a theme-rendered
WhatsApp interest link containing the product title, selected variant, and
product URL. Automatic restock detection, subscriber storage, consent
management, and outbound notification require a backend or dedicated app and
should not be implemented as unsecured client-side theme code.

## 10. Theme settings

Settings have two mirrored representations:

- `config/settings_schema.json` defines global editor controls.
- `config/settings_data.json` stores default/current values.
- `editor_config/` contains the editor equivalents.

When changing defaults:

1. Keep schema and stored values compatible.
2. Update both config directories.
3. Preserve valid JSON.
4. Do not remove a setting that Liquid still references.
5. Test existing stores where a newly introduced value may be blank.

Prefer safe Liquid fallbacks and CSS custom-property fallbacks for new settings.

## 11. EasyStore content and app hooks

Calls such as `{% app_snippet 'collection/product_top' %}` are integration
points. They allow installed EasyStore apps to inject storefront behavior.

Do not remove app hooks merely because they render nothing in a local source
review. Installed apps own any storefront UI they inject through these hooks.

## 12. Accessibility requirements

When modifying the theme:

- preserve semantic headings;
- keep visible keyboard focus;
- ensure dropdowns remain keyboard-operable;
- retain accessible names on icon-only buttons;
- keep product images supplied with meaningful alternative text;
- maintain sufficient foreground/background contrast;
- do not communicate sale or stock state using color alone;
- test mobile drawer controls and nested disclosures.

Hover behavior must have a corresponding keyboard-focus treatment when it
communicates interaction.

## 13. Safe change recipes

### Add a new stylesheet

1. Add it to `assets/`.
2. Add the identical file to `editor_assets/`.
3. Reference it from the appropriate Liquid file.
4. Run validation and tests.

### Add a new section

1. Create `sections/name.liquid`.
2. Add markup and settings access.
3. Add one valid JSON schema block.
4. Reference only assets and snippets that exist.
5. Add it to settings data only when it should be present by default.

### Add a new snippet

1. Create `snippets/name.liquid`.
2. Include or render it using a literal snippet name.
3. Document expected variables at the top when its inputs are not obvious.

### Change homepage order

1. Update `content_for_index` in both settings-data files.
2. Confirm every referenced section key exists.
3. Preserve the documented Best Sellers, Hobbit, Marvel, and Strixhaven order
   unless the merchandising strategy explicitly changes.

### Change a collection assignment

Update the section's `collection__id` in both settings-data files, or use the
EasyStore theme customizer after upload. The handle must match an existing
EasyStore collection.

## 14. Maintenance checklist

Before opening a pull request:

- [ ] Storefront and editor assets remain mirrored.
- [ ] JSON parses successfully.
- [ ] Liquid references point to existing local files.
- [ ] Section schema blocks are valid.
- [ ] Mobile and desktop behavior have both been considered.
- [ ] App hooks needed by installed apps remain present.
- [ ] Theme validation passes.
- [ ] Unit tests pass.
- [ ] The generated ZIP validates.
- [ ] Documentation and repository tooling are absent from the ZIP.

## 15. Known platform boundaries

- Navigation records, collections, products, inventory, and customer data are
  EasyStore data, not theme source.
- The system Catalog menu is generated by EasyStore.
- Product tags are searchable but are not first-class navigation targets.
- A theme cannot securely persist notification subscribers by itself.
- Checkout source is outside normal theme customization. The theme can style
  those fields but cannot add a label to them, so `base.css` keeps the
  placeholder visible for any `.field__input` with no sibling label — otherwise
  a platform-rendered field such as the checkout email input names itself
  nowhere.
- `/account/auth` may be EasyStore's own flow rather than
  `templates/customers/login.liquid`; the one-time-code step there certainly is.
  No theme deploy can change copy on a page the theme does not render. Paste
  `scripts/account-copy-check.console.js` into the browser console on the page
  to tell the two apart: it reports whether the theme's own recovery markup is
  present and which rules the published stylesheet contains, so a change that
  does not appear points either at a stale published build or at the store's
  translations.
- Copy the platform renders in that flow can still be overridden at runtime, and
  two overrides ship for it: `account-recovery-copy.js` replaces the promise of
  a reset email, and `account-otp-copy.js` hides the "continue with email
  instead" link — this store signs customers up by mobile number only, so no
  email path is offered anywhere. Both stay text-only: they read `textContent`
  and, at most, hide the control holding it. Neither writes into a field,
  dispatches an event, or removes a node, because theme scripts writing into the
  platform's verification cells are what broke signup with "Customer already
  exists (phone)". Setting the matching store translations makes each override a
  no-op, and it can be deleted at that point.
- Autofill on that one-time-code step used to drop the whole code into a single
  cell instead of spreading it across the six. `account-otp-autofill.js` fixes
  it, and the history is worth knowing before touching it, because the same
  symptom was attempted twice before and broke signup both times. PR #65 and
  PR #66 wrote the digits into the cells and dispatched `input` and `change` on
  each one; two scripts ended up writing into the same fields, the widget's own
  submit ran more than once, the second POST returned "Customer already exists
  (phone)", and every new customer was blocked until `b228492` reverted it. A
  submit lock does not help — the widget posts over `fetch`, so there is no
  submit event to intercept.
- What made a safe fix possible was reading the widget instead of guessing.
  Captured at `/account/auth/send`: six `type="number"` cells, `maxlength="1"`,
  `pattern="[0-9]"`, class `otp-input`, no `name` and no `id`, inside
  `div#otp-form > div.d-flex`, with **no `form` element** — which is why the
  reverted module never even ran here, as it gated on a form action matching a
  verification keyword. `maxlength` is inert on a number input, so all six digits
  fit in one cell; no cell sets `autocomplete`, so Android has no
  `one-time-code` target and fills whichever cell has focus. The cells carry no
  framework state, so the widget reads `value` directly. Its own handler is:

  ```js
  if (input.value.length >= 1) {
    if (index < otp_inputs.length - 1) otp_inputs[index + 1].focus();
    if (index === 5) submitOTP();
  }
  ```

  `submitOTP()` therefore has exactly one trigger: an `input` event on the last
  cell. The module fills the cells by assignment — no events, because the widget
  reads `value` — and emits that single `input` on the last cell only, which is
  the same one event a customer's sixth keystroke produces. It emits nothing when
  the code is short, so a partial verification cannot post, and it latches so a
  suggestion that fires `input` twice still hands the code over once. The
  widget's own paste path already spreads a code correctly and sets values
  without dispatching, so the module never sees it and stays out of the way.
- Re-derive all of that with `scripts/otp-widget-capture.console.js` (markup and
  whether the cells carry framework state) and `scripts/otp-handler-probe.console.js`
  (the handlers as source, out of jQuery's registry and `getEventListeners`).
  Both only read — no value set, no event dispatched, no listener added, no node
  removed, and no digits printed — so they are safe to run during a real signup.
  Neither is packaged.
- The invariant that matters here is a count, not a shape: the widget must be
  asked to submit exactly once. `e2e/otp-autofill.spec.js` asserts it by running
  the real module against a replica built from the captured markup and handlers,
  counting `submitOTP()` calls across autofill, short codes, repeat autofill,
  typing, paste, and correction. It needs no storefront, so its CI job depends on
  `validate` rather than `preflight` and keeps running when the live store is
  unreachable. `tests/test_otp_cell_autofill.py` still bans the reverted design
  by name.
- A store translation can come back empty. A field whose placeholder and
  floating label both read one key then renders with no visible title at all,
  which is how the email field on `/account/details` shipped untitled while
  every neighbouring field kept its label. Route shopper-visible copy through
  `translation-fallback.liquid` with a literal fallback, and write the copy out
  in the template when the platform text is wrong for this store — the password
  recovery paragraph does that because the platform copy promises a reset email
  while this store confirms a mobile OTP.
- Theme validation reduces known packaging and static-reference failures but
  cannot guarantee that third-party apps or future EasyStore platform changes
  will never affect runtime behavior.
