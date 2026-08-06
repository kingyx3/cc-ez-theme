from __future__ import annotations

import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
THEME_ROOT = REPOSITORY_ROOT / "theme"


class CustomerOrderLimitCopyTests(unittest.TestCase):
    """Limit copy lives in one place and is built from live quantities."""

    def read(self, relative: str) -> str:
        return (THEME_ROOT / relative).read_text(encoding="utf-8")

    def test_the_separate_copy_correction_layer_is_retired(self) -> None:
        # The helper rewrote product-form copy from its own templates, so any
        # wording added to the validator was silently dropped on the product
        # page. The validator is now the only source of limit copy.
        currencies = self.read("snippets/currencies.liquid")
        self.assertNotIn("customer-order-limit-copy", currencies)
        self.assertIn("purchase-limit-feedback.js", currencies)

        for relative in (
            "assets/customer-order-limit-copy.js",
            "editor_assets/customer-order-limit-copy.js",
        ):
            with self.subTest(relative=relative):
                self.assertFalse((THEME_ROOT / relative).exists())

        for relative in ("assets/product-form.js", "assets/buy-now-limit-checkout.js"):
            with self.subTest(relative=relative):
                self.assertNotIn("customerOrderLimitCopyEnhanced", self.read(relative))

    def test_validator_owns_the_maximum_reached_copy(self) -> None:
        limits = self.read("assets/customer-order-limits.js")

        self.assertIn("const unitLabel = (value) => {", limits)
        self.assertIn(
            "Maximum quantity reached. You have already purchased ${unitLabel(purchased)}"
            " and have ${unitLabel(cartQuantity)} in your cart.",
            limits,
        )
        self.assertIn(
            "Maximum quantity reached. You already have ${unitLabel(cartQuantity)} in your cart.",
            limits,
        )
        self.assertIn(
            "Customer purchase limit reached. You have already purchased ${unitLabel(purchased)}"
            " of the ${unitLabel(maximum)} allowed per customer across orders",
            limits,
        )
        self.assertIn("The limit is ${unitLabel(maximum)} per customer across orders", limits)
        self.assertNotIn("0 units maximum", limits)
        self.assertNotIn("in cart +", limits)

    def test_product_form_uses_the_validator_message(self) -> None:
        product = self.read("assets/product-form.js")

        # quantityLimitForHandle supplies the message, so the product page shows
        # the same wording as the listing, cart, and Buy Now surfaces.
        self.assertIn("window.CustomerOrderLimits.quantityLimitForHandle(", product)
        self.assertIn("const message = limit.message", product)

    def test_hobbit_prerelease_kit_uses_a_customer_limit_of_one(self) -> None:
        config = self.read("snippets/customer-order-limit-config.liquid")

        self.assertIn(
            "customer_order_limit_handle_7 = 'MTG-HOB-PRK-EN-SET4'",
            config,
        )
        self.assertIn("customer_order_limit_maximum_7 = 1", config)


if __name__ == "__main__":
    unittest.main()
