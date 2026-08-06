# Product listing badge safety

## Purpose

Product cards are shared across homepage collections, collection pages, search, recommendations, cart recommendations, and other storefront surfaces. A small edit to `theme/snippets/product-card.liquid` can therefore affect most of the theme.

This guide defines the safe pattern for suppressing a visual badge without removing EasyStore theme logic or depending on an optional asset.

## Incident summary

Two earlier approaches were too fragile:

1. Removing the sale-state variables and badge markup changed the vendor theme's original Liquid structure.
2. Restoring that structure but hiding the badge from `component-product-card-cart-controls.css` made the result depend on a stylesheet emitted conditionally from the product-card snippet.

Both approaches passed static validation and packaging, but those checks do not render every EasyStore page with live products, app snippets, theme-editor behavior, and final asset ordering.

## Approved implementation

For the product-listing sale badge:

- keep the original `on_sale` calculation;
- keep the translated sale label;
- keep the original conditional and badge classes;
- put `hidden="hidden"` and `aria-hidden="true"` on the sale badge container;
- do not make visibility depend on cart controls, quick view, JavaScript, or another optional asset;
- keep sold-out badges and price rendering unchanged.

The standard HTML `hidden` attribute suppresses the overlay at its markup source. This preserves EasyStore and app integration hooks while avoiding load-order and stylesheet-scope failures.

## Required checks for shared product-card changes

Before merging any change to `theme/snippets/product-card.liquid`:

1. Search every include of `product-card` and identify all affected storefront surfaces.
2. Preserve existing Liquid variables, app snippets, translated strings, classes, and data attributes unless their removal is explicitly required and has been rendered in EasyStore.
3. For critical visibility behavior, prefer a semantic attribute at the markup source. Do not rely on a stylesheet that is loaded only when another feature is enabled.
4. Update both storefront and theme-editor assets whenever an asset change is necessary, and assert that mirrored files remain identical.
5. Test the requested negative behavior and adjacent positive behavior. Here, sale overlays must be hidden while sold-out badges and sale pricing remain.
6. Run the real-theme validator, complete unit tests with coverage, and the package/revalidation workflow.
7. Inspect the downloadable ZIP and confirm the packaged Liquid—not only repository source—contains the intended attribute.
8. Preview at least one sale product and one sold-out product on desktop and mobile before publishing the theme.

## Regression coverage

`tests/test_product_listing_sale_overlays.py` protects this contract:

- the original sale-state Liquid remains present;
- every sale badge emitted by the theme is hidden at the markup source;
- visibility does not depend on the optional cart-control stylesheet;
- storefront and editor cart-control styles remain mirrored;
- sold-out badges and sale pricing remain present.

## Rollback

To show sale ribbons again, remove `hidden="hidden"` and `aria-hidden="true"` from the sale badge container. Do not remove the sale-state calculation, translated label, conditional, or badge classes.
