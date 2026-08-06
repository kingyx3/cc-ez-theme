from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
THEME = ROOT / "theme"


class BuyNowPurchaseLimitCheckoutTests(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (THEME / relative).read_text(encoding="utf-8")

    def test_storefront_and_editor_helpers_match(self) -> None:
        storefront = self.read("assets/buy-now-limit-checkout.js")
        editor = self.read("editor_assets/buy-now-limit-checkout.js")

        self.assertEqual(storefront, editor)

    def test_buy_now_stays_clickable_and_opens_existing_limit_modal(self) -> None:
        helper = self.read("assets/buy-now-limit-checkout.js")

        self.assertIn("prototype.setPurchaseButtonsLimited", helper)
        self.assertIn("this.querySelectorAll('[name=\"add\"]')", helper)
        self.assertIn("restoreBuyNowButton(this)", helper)
        self.assertIn("window.CustomerOrderLimits.additionViolation", helper)
        self.assertIn("productForm.getQuantityLimit()", helper)
        self.assertIn("productForm.openBuyNowLimitModal", helper)
        self.assertIn("event.stopImmediatePropagation()", helper)
        self.assertNotIn(
            "this.querySelectorAll('[name=\"add\"], [data-buy-now]')",
            helper,
        )

    def test_helper_loads_before_customer_order_limit_capture_handler(self) -> None:
        currencies = self.read("snippets/currencies.liquid")
        helper_position = currencies.index("buy-now-limit-checkout.js")
        limits_position = currencies.index("{% include 'customer-order-limits' %}")

        self.assertLess(helper_position, limits_position)


if __name__ == "__main__":
    unittest.main()
