from __future__ import annotations

import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
THEME_ROOT = REPOSITORY_ROOT / "theme"


class CustomerOrderLimitCopyTests(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (THEME_ROOT / relative).read_text(encoding="utf-8")

    def test_copy_helper_loads_after_contextual_purchase_feedback(self) -> None:
        currencies = self.read("snippets/currencies.liquid")
        contextual = "purchase-limit-feedback.js"
        correction = "customer-order-limit-copy.js"

        self.assertIn(contextual, currencies)
        self.assertIn(correction, currencies)
        self.assertLess(currencies.index(contextual), currencies.index(correction))

    def test_storefront_and_editor_copy_helpers_match(self) -> None:
        storefront = self.read("assets/customer-order-limit-copy.js")
        editor = self.read("editor_assets/customer-order-limit-copy.js")

        self.assertEqual(storefront, editor)
        self.assertIn("rule.maximum", storefront)
        self.assertIn("rule.purchased", storefront)
        self.assertIn("rule.cartQuantity", storefront)
        self.assertIn("prototype.showQuantityLimit", storefront)
        self.assertIn("prototype.openBuyNowLimitModal", storefront)
        self.assertIn("The limit is ${unitLabel(maximum)} per customer across orders.", storefront)
        self.assertIn("You already have ${unitLabel(cartQuantity)} in your cart.", storefront)
        self.assertIn("You have already purchased ${unitLabel(purchased)}", storefront)
        self.assertNotIn("0 units maximum", storefront)
        self.assertNotIn("in cart +", storefront)

    def test_hobbit_prerelease_kit_uses_a_customer_limit_of_one(self) -> None:
        config = self.read("snippets/customer-order-limit-config.liquid")

        self.assertIn(
            "customer_order_limit_handle_7 = 'MTG-HOB-PRK-EN-SET4'",
            config,
        )
        self.assertIn("customer_order_limit_maximum_7 = 1", config)


if __name__ == "__main__":
    unittest.main()
