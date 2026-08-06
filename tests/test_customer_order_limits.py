from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
THEME = ROOT / "theme"


class CustomerOrderLimitTests(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (THEME / relative).read_text(encoding="utf-8")

    def test_exact_limit_matrix_is_preserved(self) -> None:
        config = self.read("snippets/customer-order-limit-config.liquid")
        expected = (
            (1, "MTG-HOB-BDL-EN", 2),
            (2, "MTG-HOB-CBB-EN", 2),
            (3, "MTG-HOB-CBB-EN-CASE6", 1),
            (4, "MTG-HOB-CBB-EN-PACK", 1),
            (5, "MTG-HOB-DNK-EN", 3),
            (6, "MTG-HOB-GFB-EN", 1),
            (7, "MTG-HOB-PBB-EN", 12),
            (8, "MTG-HOB-PRK-EN-SET4", 1),
            (9, "MTG-HOB-OBP-EN", 1),
            (10, "MTG-HOB-SCN-EN-SET2", 1),
        )
        for slot, handle, maximum in expected:
            self.assertIn(
                f"customer_order_limit_handle_{slot} = '{handle}'",
                config,
            )
            self.assertIn(
                f"customer_order_limit_maximum_{slot} = {maximum}",
                config,
            )
        self.assertIn("normalized to lowercase", config)
        self.assertNotIn("split:", config)

    def test_liquid_normalizes_both_configured_and_storefront_handles(self) -> None:
        liquid = self.read("snippets/customer-order-limits.liquid")
        rule = self.read("snippets/customer-order-limit-rule.liquid")
        self.assertEqual(liquid.count("{% for order in customer.orders %}"), 1)
        self.assertEqual(liquid.count("{% for line_item in order.line_items %}"), 1)
        self.assertEqual(liquid.count("{% for cart_item in cart.items %}"), 1)
        self.assertEqual(
            liquid.count("{% include 'customer-order-limit-rule'"),
            10,
        )
        self.assertIn("customer_order_limit_handle_10_normalized", liquid)
        self.assertIn("line_item.product.handle", liquid)
        self.assertIn("cart_item.product.handle", liquid)
        self.assertGreaterEqual(liquid.count("| downcase"), 12)
        self.assertIn("rule_handle | default: '' | strip | downcase", rule)
        self.assertNotIn("customer.orders | json", liquid)
        self.assertNotIn("EasyStore.Action", liquid)

    def test_shared_validator_normalizes_and_guards_all_purchase_surfaces(self) -> None:
        storefront = self.read("assets/customer-order-limits.js")
        editor = self.read("editor_assets/customer-order-limits.js")
        self.assertEqual(storefront, editor)
        for expected in (
            "toLowerCase()",
            "decodeURIComponent",
            "quantityLimitForHandle",
            "additionViolation",
            "cartViolationFromForm",
            "commitCartTotals",
            "recordAddition",
            "recordRemoval",
            "[data-buy-now]",
            "name === 'expresscheckout'",
            "customerOrderLimitCheckoutBlocked",
        ):
            self.assertIn(expected, storefront)
        self.assertNotIn("MutationObserver", storefront)
        self.assertNotIn("EasyStore.Action", storefront)
        self.assertNotIn("window.location.reload()", storefront)
        self.assertNotRegex(
            storefront,
            re.compile(r"\.prototype\.[A-Za-z_$][\w$]*\s*="),
        )

    def test_native_product_listing_and_cart_paths_enforce_limits(self) -> None:
        product = self.read("assets/product-form.js")
        listing = self.read("assets/product-card-cart-feedback.js")
        cart = self.read("assets/cart.js")
        self.assertEqual(product, self.read("editor_assets/product-form.js"))
        self.assertEqual(
            listing,
            self.read("editor_assets/product-card-cart-feedback.js"),
        )
        self.assertEqual(cart, self.read("editor_assets/cart.js"))
        self.assertIn("quantityLimitForHandle", product)
        self.assertIn("CustomerOrderLimits.productHandle(this.form)", product)
        self.assertIn("recordAddition", product)
        self.assertIn("cartViolation()", product)
        self.assertIn("additionViolation", listing)
        self.assertIn("recordAddition", listing)
        self.assertIn("cartViolationFromForm", cart)
        self.assertIn("allowDecreases: true", cart)
        self.assertIn("commitCartTotals", cart)
        self.assertIn("recordRemoval", cart)

    def test_dynamic_product_and_cart_markup_carries_stable_handles(self) -> None:
        featured = self.read("sections/featured-product.liquid")
        quickview = self.read("snippets/product-quickview.liquid")
        cart_item = self.read("snippets/cart-item.liquid")
        self.assertIn(
            'data-product-handle="{{ featured_product.handle | downcase | escape }}"',
            featured,
        )
        self.assertIn(
            'data-product-handle="{{ product.handle | downcase | escape }}"',
            quickview,
        )
        self.assertIn('name="product_handles[]"', cart_item)
        self.assertIn("item.product.handle", cart_item)
        self.assertIn("| downcase | escape", cart_item)

    def test_loader_and_pr56_rollback_remain_intact(self) -> None:
        currencies = self.read("snippets/currencies.liquid")
        self.assertIn("{% include 'customer-order-limits' %}", currencies)
        self.assertIn("purchase-limit-feedback.js", currencies)
        self.assertIn("EasyStore.Currencies.init", currencies)
        for relative in (
            "assets/customer-purchase-limits.js",
            "editor_assets/customer-purchase-limits.js",
            "snippets/customer-purchase-limits.liquid",
        ):
            self.assertFalse((THEME / relative).exists())


if __name__ == "__main__":
    unittest.main()
