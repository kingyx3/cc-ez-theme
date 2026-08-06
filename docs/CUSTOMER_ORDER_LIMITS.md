# Customer order limits

This feature limits a signed-in customer to a configured number of units for an EasyStore product handle across non-cancelled orders and the current cart.

## Configured limits

| EasyStore product handle | Per-customer maximum |
| --- | ---: |
| `MTG-HOB-BDL-EN` | 2 |
| `MTG-HOB-CBB-EN` | 2 |
| `MTG-HOB-CBB-EN-CASE6` | 1 |
| `MTG-HOB-CBB-EN-PACK` | 1 |
| `MTG-HOB-DNK-EN` | 3 |
| `MTG-HOB-GFB-EN` | 1 |
| `MTG-HOB-PBB-EN` | 12 |
| `MTG-HOB-PRK-EN-SET4` | 1 |
| `MTG-HOB-OBP-EN` | 1 |
| `MTG-HOB-SCN-EN-SET2` | 1 |

The values remain explicit in `theme/snippets/customer-order-limit-config.liquid`. Every configured and storefront handle is normalized to lowercase before comparison because EasyStore product URLs use lowercase handles even when administrative values are capitalized.

## Enforcement

Liquid makes one pass through `customer.orders` and one pass through `cart.items`, combining quantities for all variants with the same normalized product handle. Cancelled orders are ignored.

The shared validator integrates with the native theme paths:

- product page, featured product, and quick-view quantity validation;
- Add to Cart and Buy Now;
- listing quick-add;
- cart quantity updates;
- standard checkout, express checkout, and additional checkout controls.

Successful additions and cart updates change the browser-side allowance only after EasyStore's native callback confirms success. Rejected requests do not consume allowance. Cart decreases and removals remain available so an over-limit cart can be corrected.

## Root cause corrected

The first deployed version compared uppercase configured handles with lowercase storefront handles, so no rule matched. It also relied mainly on document listeners and missed native Buy Now and cart paths. The corrected version normalizes both sides and validates inside the existing product, listing, and cart components, with delegated capture guards as defense in depth.

## Preview validation

Before merging or publishing, upload the exact workflow ZIP to an unpublished EasyStore theme and verify:

1. each configured handle permits its maximum but blocks one additional unit;
2. prior non-cancelled order quantities reduce the remaining allowance;
3. multiple variants and cart lines for one handle are combined;
4. Add to Cart, Buy Now, listing quick-add, cart increases, standard checkout, and express checkout are blocked when over limit;
5. cart decreases and removals continue to work;
6. rejected requests do not reduce the remaining allowance.

## Enforcement boundary

This is a theme-level storefront safeguard, not server-side authorization. Disabled JavaScript, modified clients, direct API calls, stale tabs, and other sales channels can bypass theme code. Hard enforcement requires an EasyStore server-side app or checkout validation capability.

## Rollback

Set every `customer_order_limit_handle_N` to `''` and every maximum to `0`, or deploy the known-good PR #61 artifact.
