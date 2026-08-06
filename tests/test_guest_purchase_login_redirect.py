from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
THEME = ROOT / "theme"

MIRRORED_ASSETS = (
    "buy-now-limit-checkout.js",
    "cart.js",
    "customer-order-limit-copy.js",
    "customer-order-limits.js",
    "product-card-cart-feedback.js",
    "product-form.js",
)


class GuestPurchaseLoginRedirectTests(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (THEME / relative).read_text(encoding="utf-8")

    def test_storefront_and_editor_purchase_paths_stay_mirrored(self) -> None:
        for filename in MIRRORED_ASSETS:
            with self.subTest(filename=filename):
                self.assertEqual(
                    self.read(f"assets/{filename}"),
                    self.read(f"editor_assets/{filename}"),
                )

    def test_validator_treats_login_as_the_guest_outcome(self) -> None:
        limits = self.read("assets/customer-order-limits.js")

        self.assertIn("const customerAuthenticated = source.customerAuthenticated === true;", limits)
        self.assertIn("!customerAuthenticated || rule.loginRequired === true", limits)
        self.assertIn("/account/login?redirect_uri=${encodeURIComponent(target)}", limits)
        self.assertIn("window.location.assign(loginRedirectUrl())", limits)
        for exported in (
            "loginRequiredForHandle,",
            "loginRequiredForCart,",
            "loginRequiredForCartForm,",
            "loginRedirectUrl,",
            "redirectToLogin,",
        ):
            with self.subTest(exported=exported):
                self.assertIn(exported, limits)

    def test_guests_are_never_measured_against_a_limit(self) -> None:
        limits = self.read("assets/customer-order-limits.js")

        # remainingForHandle, additionViolation, and quantityLimitForHandle all
        # report "no limit applies" for a shopper who has to sign in first.
        self.assertEqual(
            limits.count("if (!rule || loginRequiredForRule(rule)) return null;"),
            3,
        )
        # Cart totals and cart-form decoration skip login-required rules, so a
        # guest keeps native quantity inputs and an enabled checkout button.
        self.assertIn("if (loginRequiredForRule(rule)) continue;", limits)
        self.assertIn(
            "if (!input || !rule || loginRequiredForRule(rule)) return;",
            limits,
        )
        self.assertIn(
            "const allowedCartQuantity = (rule) => quantity(rule && rule.allowedCartQuantity, 0);",
            limits,
        )
        self.assertNotIn("Sign in to purchase", limits)

    def test_add_to_cart_and_buy_now_send_guests_to_login(self) -> None:
        limits = self.read("assets/customer-order-limits.js")
        listing = self.read("assets/product-card-cart-feedback.js")
        buy_now = self.read("assets/buy-now-limit-checkout.js")

        self.assertIn("if (loginRequiredForHandle(listingButton.dataset.productHandle)) {", limits)
        self.assertIn("if (loginRequiredForHandle(handle) || loginRequiredForCart()) {", limits)
        self.assertIn("if (loginRequiredForHandle(handle)) {", limits)
        self.assertEqual(limits.count("sendToLogin(event);"), 5)
        self.assertIn("event.stopImmediatePropagation();", limits)

        self.assertIn(
            "limits.loginRequiredForHandle(this.button.dataset.productHandle)",
            listing,
        )
        self.assertIn("limits.redirectToLogin();", listing)

        self.assertIn("limits.loginRequiredForHandle(productHandle(form))", buy_now)
        self.assertIn("limits.redirectToLogin();", buy_now)

    def test_checkout_paths_send_guests_to_login(self) -> None:
        cart = self.read("assets/cart.js")
        product = self.read("assets/product-form.js")
        limits = self.read("assets/customer-order-limits.js")

        self.assertIn("if (api.loginRequiredForCartForm(form)) {", cart)
        self.assertIn("api.redirectToLogin();", cart)
        self.assertIn("if (limits && limits.loginRequiredForCart()) {", product)
        self.assertIn("limits.redirectToLogin();", product)
        self.assertEqual(limits.count("if (loginRequiredForCartForm("), 2)

    def test_limit_copy_no_longer_targets_guests(self) -> None:
        copy = self.read("assets/customer-order-limit-copy.js")

        self.assertNotIn("loginRequired", copy)
        self.assertNotIn("Sign in to purchase", copy)
        self.assertIn(
            "const customerLimitReached = remaining != null && selectedQuantity >= remaining;",
            copy,
        )

    def test_liquid_keeps_the_login_flag_without_zeroing_the_allowance(self) -> None:
        rule = self.read("snippets/customer-order-limit-rule.liquid")

        self.assertIn("loginRequired: {{ customer_order_limit_rule_login_required | json }},", rule)
        self.assertIn("{% if rule_customer_authenticated %}", rule)
        self.assertNotIn(
            "{% if customer_order_limit_rule_login_required %}\n"
            "    {% assign customer_order_limit_rule_allowed_cart_quantity = 0 %}",
            rule,
        )
        self.assertEqual(
            rule.count("{% assign customer_order_limit_rule_allowed_cart_quantity = 0 %}"),
            1,
        )


if __name__ == "__main__":
    unittest.main()
