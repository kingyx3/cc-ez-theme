from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
THEME = ROOT / "theme"


class BuyNowCheckoutJourneyTests(unittest.TestCase):
    """Guards the Buy Now journey for a product at its customer purchase limit."""

    def read(self, relative: str) -> str:
        return (THEME / relative).read_text(encoding="utf-8")

    def test_limit_guards_never_intercept_the_buy_now_checkout_form(self) -> None:
        limits = self.read("assets/customer-order-limits.js")
        product_section = self.read("sections/main-product.liquid")

        # The checkout form lives inside <product-form>, so a `product-form form`
        # guard would block checkout and strand the shopper mid-purchase.
        self.assertIn("<form action=\"/cart\" method=\"post\" data-buy-now-checkout-form hidden>", product_section)
        self.assertIn("const isAddToCartForm = (form) => (", limits)
        self.assertIn("!form.matches('[data-buy-now-checkout-form]')", limits)
        self.assertIn("form.querySelector('[name=\"add\"]')", limits)
        self.assertIn("/\\/cart\\/add/.test(String(form.getAttribute('action') || ''))", limits)
        self.assertIn("if (isAddToCartForm(form)) {", limits)
        # The bare selector must not gate an addition guard anywhere.
        self.assertEqual(limits.count("form.matches('product-form form')"), 1)

    def test_buy_now_at_the_limit_checks_out_with_the_cart_it_has(self) -> None:
        helper = self.read("assets/buy-now-limit-checkout.js")
        limits = self.read("assets/customer-order-limits.js")

        for source in (helper, limits):
            with self.subTest(source=source[:40]):
                self.assertIn("cartQuantityForHandle(handle) > 0", source)
                self.assertIn("remaining <= 0", source)
        self.assertIn("cartQuantityForHandle,", limits)
        self.assertIn("owner.goToCheckout();", limits)

    def test_buy_now_releases_its_buttons_when_checkout_does_not_start(self) -> None:
        product = self.read("assets/product-form.js")

        self.assertIn("if (!this.goToCheckout()) {\n            setSubmitting(false);", product)
        self.assertIn("window.setTimeout(() => setSubmitting(false), 8000);", product)
        # goToCheckout reports its outcome instead of returning silently.
        self.assertIn("        this.renderErrorMsg(customerOrderLimitViolation.message);\n        return false;", product)
        self.assertIn("        window.location.assign('/cart');\n        return true;", product)
        self.assertIn("      return true;\n    }", product)

    def test_limit_copy_is_built_from_live_quantities(self) -> None:
        limits = self.read("assets/customer-order-limits.js")

        # Server-rendered copy goes stale as soon as the cart changes, which is
        # how "you can add up to 1 more" ended up on a maxed-out product.
        self.assertNotIn("rule.message", limits.replace("`rule.message`", ""))
        self.assertIn("const messageFor = (rule, requestedQuantity, remaining) => {", limits)
        self.assertIn("const cartMessageFor = (rule, allowed) => {", limits)
        self.assertIn("You have ${cartQuantity} in your cart.", limits)
        self.assertIn("You can add ${moreUnits(remaining)}.", limits)
        self.assertIn("Reduce this item to ${unitLabel(allowed)} to check out", limits)
        self.assertIn("Remove this item to check out.", limits)
        self.assertIn("Limit reached: ${unitLabel(maximum)} per customer.", limits)

    def test_storefront_and_editor_journey_assets_match(self) -> None:
        for filename in (
            "buy-now-limit-checkout.js",
            "customer-order-limits.js",
            "product-form.js",
        ):
            with self.subTest(filename=filename):
                self.assertEqual(
                    self.read(f"assets/{filename}"),
                    self.read(f"editor_assets/{filename}"),
                )


if __name__ == "__main__":
    unittest.main()
