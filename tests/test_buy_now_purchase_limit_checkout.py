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
        self.assertIn("limits.additionViolation(handle, requestedQuantity)", helper)
        self.assertIn("productForm.getQuantityLimit()", helper)
        self.assertIn("productForm.openBuyNowLimitModal", helper)
        self.assertIn("event.stopImmediatePropagation()", helper)

    def test_buy_now_checks_out_when_the_cart_already_holds_the_allowance(self) -> None:
        helper = self.read("assets/buy-now-limit-checkout.js")

        # Nothing more may be added, but the shopper already owns the allowance in
        # their cart, so Buy Now must reach checkout instead of retrying the add.
        self.assertIn("customerViolation.remaining <= 0", helper)
        self.assertIn("limits.cartQuantityForHandle(handle) > 0", helper)
        self.assertIn("productForm.goToCheckout();", helper)
        self.assertLess(
            helper.index("productForm.goToCheckout();"),
            helper.index("productForm.openBuyNowLimitModal(String(message))"),
        )
        self.assertNotIn(
            "this.querySelectorAll('[name=\"add\"], [data-buy-now]')",
            helper,
        )

    def test_page_product_cart_is_counted_by_variant_id(self) -> None:
        # The Liquid limit passes count cart lines by handle or SKU, which a cart
        # line may not expose. Counting 0 let Buy Now add a unit past the limit
        # and go straight to checkout; e2e/buy-now-cart-limit.spec.js drives it.
        for relative in ("customer-order-limits.js", "per-order-limits.js"):
            for folder in ("assets", "editor_assets"):
                module = self.read(f"{folder}/{relative}")
                self.assertIn("window.purchaseCartQuantities || {}", module)
                self.assertIn("reconcilePageCart();", module)

        customer = self.read("assets/customer-order-limits.js")
        self.assertLess(
            customer.index("reconcilePageCart();"),
            customer.index("new CustomEvent('customer-order-limits:ready')"),
        )

        workflow = (ROOT / ".github/workflows/e2e-theme.yml").read_text(encoding="utf-8")
        self.assertIn("e2e/buy-now-cart-limit.spec.js", workflow)

    def test_helper_loads_before_customer_order_limit_capture_handler(self) -> None:
        currencies = self.read("snippets/currencies.liquid")
        helper_position = currencies.index("buy-now-limit-checkout.js")
        limits_position = currencies.index("{% include 'customer-order-limits' %}")

        self.assertLess(helper_position, limits_position)


if __name__ == "__main__":
    unittest.main()
