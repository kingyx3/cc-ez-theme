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

The desktop header and mobile drawer expose a Browse dropdown followed by four
top-level destinations in a fixed order:

1. Browse (EasyStore product collection hierarchy)
2. Hobbit (`/collections/the-hobbit`)
3. Marvel (`/collections/marvel-super-heroes`)
4. Strixhaven (`/collections/secrets-of-strixhaven`)
5. About Us (`/pages/about-us`)

About Us is pushed to the right edge of the desktop navigation area. The
Browse reads `contents.catalog.links` and renders up to three collection levels
from EasyStore's product catalog hierarchy. On desktop, hovering or focusing a
parent collection opens its child collection flyout; mobile retains nested
drill-down navigation. The three fixed collection shortcuts remain direct
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

## 9. Out-of-stock interest

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
- The one-time-code cells on that step cannot be fixed from the theme without
  the widget's real markup, and guessing at them has already cost an outage. On
  Android the keyboard's autofill drops the whole code into one cell instead of
  one digit per cell. Two attempts to spread it across the cells shipped and
  were reverted the same day: the widget posts its verification over `fetch`,
  every synthetic `input` or `change` event drove that path again, and the
  second POST came back "Customer already exists (phone)", which broke signup
  for every new phone number. A submit-event lock cannot deduplicate a `fetch`.
  Switching the step to a single wide input is not available either — the theme
  does not render it, so there is no template to change.
  `tests/test_otp_cell_autofill.py` holds that line: no shipped script may claim
  one-time-code fields or dispatch events into them.
  Paste `scripts/otp-widget-probe.console.js` into the console on the live step
  (Android over `chrome://inspect`) to capture what a safe fix needs: the cells'
  real count and attributes, whether a `<form>` or a framework owns them, and
  how many verification requests the widget already fires by itself. It is
  read-only — it never writes a cell or dispatches an event — and it masks
  digits, so the report can be shared without leaking a live code or a phone
  number. Design the fix against that report, not against assumed markup.
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
