from __future__ import annotations

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

        self.assertIn("{% include 'per-order-limit-config' %}", customer)
        self.assertIn("per-order-limits.js", customer)
        self.assertIn("window.perOrderLimitsV1", customer)
        self.assertIn("separate from customer-order-limit-config.liquid", order)
        self.assertIn("order_limit_handle", order)
        self.assertIn("order_limit_maximum", order)
        self.assertNotIn("limit_refresh", order)

    def test_order_row_matches_handle_or_sku_and_publishes_cart_total(self) -> None:
        row = self.read("snippets/per-order-limit-row.liquid")

        self.assertIn("cart_item.product.handle", row)
        self.assertIn("cart_item.sku", row)
        self.assertIn("per_order_limit_row_cart | plus:", row)
        self.assertIn("window.perOrderLimitsV1.rules", row)
        self.assertIn("maximum:", row)
        self.assertIn("cartQuantity:", row)
        self.assertIn("{% assign order_limit_handle = '' %}", row)
        self.assertIn("{% assign order_limit_maximum = 0 %}", row)

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
