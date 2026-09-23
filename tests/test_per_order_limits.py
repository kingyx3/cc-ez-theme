from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
THEME = ROOT / "theme"


class PerOrderLimitTests(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (THEME / relative).read_text(encoding="utf-8")

    def test_per_order_configuration_is_separate_from_customer_limits(self) -> None:
        customer = self.read("snippets/customer-order-limit-config.liquid")
        order = self.read("snippets/per-order-limit-config.liquid")

        self.assertIn("{% include 'per-order-limits' %}", customer)
        self.assertIn("separate from customer-order-limit-config.liquid", order)
        self.assertIn("order_limit_handle", order)
        self.assertIn("order_limit_maximum", order)
        self.assertIn("A single row is the whole configuration change", order)
        self.assertNotIn("limit_refresh", order)
        self.assertNotIn("wildcard", order.lower())

    def test_one_exact_row_is_the_whole_change_for_a_new_handle(self) -> None:
        config = self.read("snippets/per-order-limit-config.liquid")
        row = self.read("snippets/per-order-limit-row.liquid")

        example = (
            "{% include 'per-order-limit-row', order_limit_handle: "
            "'MTG-HOB-CBB-EN', order_limit_maximum: 2 %}"
        )
        self.assertIn(example, config)
        self.assertIn("Adding or changing an order limit is one row", row)
        self.assertIsNone(re.search(r"per_order_limit_\w*_\d", row))
        self.assertIsNone(re.search(r"order_limit_(handle|maximum)_\d", config))
        self.assertIn("{% assign order_limit_handle = '' %}", row)
        self.assertIn("{% assign order_limit_maximum = 0 %}", row)

    def test_cart_is_scanned_once_for_all_order_rows(self) -> None:
        bootstrap = self.read("snippets/per-order-limits.liquid")
        row = self.read("snippets/per-order-limit-row.liquid")

        self.assertEqual(bootstrap.count("{% for cart_item in cart.items %}"), 1)
        self.assertIn("cart_item.product.handle", bootstrap)
        self.assertIn("cart_item.sku", bootstrap)
        self.assertIn("window.perOrderLimitsV1 = { rules: {}, cart: {} }", bootstrap)
        self.assertIn("{% include 'per-order-limit-config' %}", bootstrap)
        self.assertIn("per-order-limits.js", bootstrap)
        self.assertNotIn("{% for cart_item in cart.items %}", row)
        self.assertIn("window.perOrderLimitsV1.rules", row)
        self.assertIn("maximum:", row)
        self.assertIn("cartQuantity: window.perOrderLimitsV1.cart", row)

    def test_order_validator_is_independent_and_layered_with_customer_validator(self) -> None:
        storefront = self.read("assets/per-order-limits.js")
        editor = self.read("editor_assets/per-order-limits.js")

        self.assertEqual(storefront, editor)
        for expected in (
            "per order",
            "quantityLimitForHandle",
            "additionViolation",
            "cartViolationFromForm",
            "recordAddition",
            "recordRemoval",
            "perOrderLimitsWrapped",
            "strictest",
            "[data-buy-now]",
            "name !== 'expresscheckout'",
        ):
            self.assertIn(expected, storefront)

        self.assertNotIn("loadHistory", storefront)
        self.assertNotIn("HISTORY_URL", storefront)
        self.assertNotIn("redirectToLogin", storefront)


if __name__ == "__main__":
    unittest.main()
