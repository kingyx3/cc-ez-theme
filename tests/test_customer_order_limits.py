from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from limit_config import configured_rows, row_liquid  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
THEME = ROOT / "theme"


class CustomerOrderLimitTests(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (THEME / relative).read_text(encoding="utf-8")

    def test_exact_limit_matrix_is_preserved(self) -> None:
        config = self.read("snippets/customer-order-limit-config.liquid")
        expected = (
            ("MTG-HOB-BDL-EN", 6),
            ("MTG-HOB-CBB-EN", 1),
            ("MTG-HOB-CBB-EN-CASE6", 1),
            ("MTG-HOB-CBB-EN-PACK", 2),
            ("MTG-HOB-DNK-EN", 3),
            ("MTG-HOB-PBB-EN", 12),
            ("MTG-HOB-PRK-EN-SET4", 3),
            ("MTG-HOB-OBP-EN", 1),
            ("MTG-HOB-SCN-EN-SET2", 2),
            ("CC-BDL-SCENES3-EN", 1),
            ("CC-BDL-FRIENDS3-EN-SPM", 1),
            ("CC-BDL-FRIENDS3-EN-MSH", 1),
            ("CC-BDL-SPIDERVAULT-EN", 1),
            ("CC-BDL-UNEXPECTED-EN", 2),
            ("MTG-HOB-GFB-EN", 1),
            ("MTG-MSH-JBB-EN", 6),
            ("MTG-MSH-CMD-EN-CE-SET4", 1),
        )
        rows = configured_rows(config)
        self.assertEqual([(handle, maximum) for handle, maximum, _ in rows], list(expected))

        unlimited = (
            "MTG-MSH-BGB-EN",
            "MTG-MSH-CBB-EN",
            "MTG-MSH-DNK-EN",
            "MTG-MSH-GFB-EN",
            "MTG-MSH-PBB-EN",
            "MTG-MSH-SCN-EN-SET2",
            "MTG-MSH-PRK-EN-SET4",
            "MTG-MSH-CMD-EN-SET4",
            "MTG-MSH-CBB-JP",
            "MTG-SOS-CDX-EN",
            "MTG-SOS-CBB-EN",
            "MTG-SOS-DNK-EN",
            "MTG-SOS-PBB-EN",
            "MTG-SPM-CBB-EN",
            "MTG-SPM-GFB-EN",
            "MTG-SPM-PBB-EN",
            "MTG-SPM-SCN-EN",
            "MTG-SPM-CBB-JP",
            "CC-BDL-HAPPYHAMPER-EN",
            "CC-BDL-HAPPYHAMPER-EN-PBB",
        )
        for handle in unlimited:
            self.assertNotIn(handle, config)

        self.assertEqual(len(rows), 17)
        self.assertIn("normalized to lowercase", config)
        self.assertIn("Delete the row to leave a product", config)
        self.assertNotIn("split:", config)

    def test_a_limit_is_one_row_of_configuration(self) -> None:
        # A limit used to be spread over seven numbered places in two files, so a
        # product added to some of them but not all enforced nothing. Everything
        # a limit needs now travels on its own row.
        config = self.read("snippets/customer-order-limit-config.liquid")
        row = self.read("snippets/customer-order-limit-row.liquid")

        for handle, maximum, refresh in configured_rows(config):
            with self.subTest(handle=handle):
                self.assertIn(row_liquid(handle, maximum, refresh), config)
        # No numbered slots survive anywhere: a row carries its own handle,
        # maximum, refresh window, counts and published rule.
        self.assertIsNone(re.search(r"customer_order_limit_(handle|maximum|refresh)_\d", config))
        self.assertIsNone(
            re.search(r"customer_order_limit_\w*_\d", self.read("snippets/customer-order-limits.liquid"))
        )
        self.assertEqual(row.count("{% include 'customer-order-limit-rule'"), 1)
        self.assertEqual(row.count("{% include 'customer-order-limit-window'"), 1)
        # `include` shares the caller's scope on EasyStore, so a row that omits
        # limit_refresh must not inherit the previous row's timestamp.
        self.assertIn("{% assign limit_handle = '' %}", row)
        self.assertIn("{% assign limit_maximum = 0 %}", row)
        self.assertIn("{% assign limit_refresh = '' %}", row)

    def test_liquid_normalizes_handles_and_passes_authentication_explicitly(self) -> None:
        liquid = self.read("snippets/customer-order-limits.liquid")
        row = self.read("snippets/customer-order-limit-row.liquid")
        rule = self.read("snippets/customer-order-limit-rule.liquid")
        # One pass each per row, over collections resolved with a fallback name
        # so a different EasyStore field name cannot silently read nothing.
        self.assertEqual(row.count("{% for order in customer_order_limit_row_orders %}"), 1)
        self.assertEqual(row.count("{% for line_item in customer_order_limit_row_lines %}"), 1)
        self.assertEqual(row.count("{% for cart_item in cart.items %}"), 1)
        self.assertIn("customer.orders | default: customer.recent_orders", row)
        self.assertIn("order.line_items | default: order.items", row)
        self.assertIn(
            "rule_customer_authenticated: customer_order_limit_customer_authenticated",
            row,
        )
        self.assertIn("{% if customer_order_limit_customer_authenticated %}", row)
        self.assertIn("customer_order_limit_customer_id != '' or customer_order_limit_customer_email != ''", liquid)
        self.assertIn("customer.id | default: '' | append: '' | strip", liquid)
        self.assertIn("customerAuthenticated:", liquid)
        self.assertIn("limit_handle | default: '' | append: '' | strip | downcase", row)
        self.assertIn("line_item.product.handle", row)
        self.assertIn("cart_item.product.handle", row)
        self.assertIn("rule_handle | default: '' | append: '' | strip | downcase", rule)
        # `blank` comparisons are not portable across Liquid engines.
        self.assertNotIn("blank", rule)
        self.assertIn("{% if rule_customer_authenticated %}", rule)
        self.assertNotIn("{% unless customer %}", rule)
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
        self.assertIn('data-product-handle=', cart_item)
        self.assertIn("item.product.handle", cart_item)
        self.assertIn("| downcase | escape", cart_item)
        self.assertNotIn('name="product_handles[]"', cart_item)

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
