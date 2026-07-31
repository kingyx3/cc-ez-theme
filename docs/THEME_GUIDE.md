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
collections, navigation records, wishlists, and installed apps remain managed
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

The desktop header and mobile drawer expose four top-level destinations in a
fixed order:

1. Categories
2. Hobbit (`/collections/the-hobbit`)
3. Marvel (`/collections/marvel-super-heroes`)
4. About Us (`/pages/about-us`)

About Us is pushed to the right edge of the desktop navigation area. The
Categories dropdown uses the children of an EasyStore Main Menu item named
Categories when available; otherwise it falls back to the other published
Main Menu links. Wishlist links are filtered by both title and URL at every
rendered header navigation level.

The theme controls:

- visual treatment;
- a single-row desktop layout with the logo directly before navigation;
- carets and disclosure behavior;
- desktop dropdown positioning;
- mobile drawer behavior;
- the fixed shortcut destinations;
- supported rendering depth inside Categories.

The Categories menu follows EasyStore's configured handles through three
nested collection levels on desktop and mobile, matching the original header
hierarchy behavior.

### Catalog behavior

EasyStore's system Catalog navigator automatically exposes published
collections and their sub-collections. This can include both set collections
and product-type collections even if they were not manually added to Main
Menu.

For a curated storefront:

1. Hide the system Catalog navigator.
2. Create a custom Shop navigator.
3. Add only the sales-relevant collection links.
4. Group them under Shop by Set and Shop by Product Type.

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

## 9. Wishlist and out-of-stock interest

The store can use EasyStore's Wishlist integration to measure interest.
Wishlist behavior belongs to the installed EasyStore app; the theme should
leave product-level app hooks intact. Wishlist destinations are deliberately
filtered out of the desktop header navigation.

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
review. Confirm the impact on installed apps such as Wishlist before changing
them.

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
3. Keep Best Sellers and The Hobbit Collection first unless the merchandising
   strategy explicitly changes.

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
- Checkout source is outside normal theme customization.
- Theme validation reduces known packaging and static-reference failures but
  cannot guarantee that third-party apps or future EasyStore platform changes
  will never affect runtime behavior.
