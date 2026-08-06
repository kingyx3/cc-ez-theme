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

    def test_layout_and_header_publish_sign_in_state(self) -> None:
        layout = self.read("layout/theme.liquid")
        header = self.read("sections/header.liquid")

        # The layout class is the strongest signed-in signal and is present on
        # every storefront page, so the validator must be able to rely on it.
        self.assertIn("{% if customer %}customer-logged-in {% endif %}", layout)

        # Both markers are rendered from the header's own `{% if customer %}`
        # branches, once for the account icon and once for the menu drawer.
        self.assertEqual(header.count('data-customer-authenticated="true"'), 2)
        self.assertEqual(header.count('data-customer-authenticated="false"'), 2)
        self.assertLess(
            header.index('data-customer-authenticated="true"'),
            header.index('data-customer-authenticated="false"'),
        )

    def test_liquid_uses_the_theme_wide_customer_check(self) -> None:
        liquid = self.read("snippets/customer-order-limits.liquid")

        self.assertIn("{% if customer %}", liquid)
        self.assertIn("customer.id != blank or customer.email != blank", liquid)
        self.assertIn("customerAuthenticated:", liquid)
        # The flag is only ever raised to true, so a missing identity field can
        # never mark a signed-in customer as a guest.
        self.assertEqual(
            liquid.count("{% assign customer_order_limit_customer_authenticated = true %}"),
            2,
        )
        self.assertEqual(
            liquid.count("{% assign customer_order_limit_customer_authenticated = false %}"),
            1,
        )

    def test_redirect_requires_proof_that_the_shopper_is_signed_out(self) -> None:
        limits = self.read("assets/customer-order-limits.js")

        self.assertIn(
            "const SIGNED_IN_MARKUP = 'body.customer-logged-in, "
            "[data-customer-authenticated=\"true\"], a[href^=\"/account/logout\"]';",
            limits,
        )
        self.assertIn(
            "const SIGNED_OUT_MARKUP = '[data-customer-authenticated=\"false\"]';",
            limits,
        )
        # A signed-in marker, the Liquid hint, or an account page all settle the
        # question as "not signed out" before the guest marker is consulted.
        self.assertIn("if (customerAuthenticated || onAccountPage()) {", limits)
        self.assertIn("if (document.querySelector(SIGNED_IN_MARKUP)) {", limits)
        # Unproven state never redirects, and stays unproven so a later render
        # can still settle it.
        self.assertIn("if (!document.querySelector(SIGNED_OUT_MARKUP)) return false;", limits)
        self.assertIn("const loginRequiredForRule = (rule) => Boolean(rule) && shopperSignedOut();", limits)
        self.assertIn("if (!shopperSignedOut()) return false;", limits)
        self.assertIn("/^\\/account(\\/|$)/.test(String(window.location.pathname || ''))", limits)

    def test_redirect_helpers_report_whether_they_navigated(self) -> None:
        limits = self.read("assets/customer-order-limits.js")

        # Callers must be able to fall through to native behaviour when no
        # redirect happened, so both helpers return a boolean and every caller
        # guards its preventDefault on that result.
        self.assertIn("    return redirectToLogin();\n  };", limits)
        self.assertIn("if (loginRequiredForHandle(handle) && sendToLogin(event)) return;", limits)
        self.assertIn(
            "        loginRequiredForHandle(listingButton.dataset.productHandle)\n"
            "        && sendToLogin(event)\n"
            "      ) return;",
            limits,
        )
        self.assertIn("if (loginRequiredForCartForm(cartForm) && sendToLogin(event)) return;", limits)
        self.assertIn("if (loginRequiredForCartForm(form) && sendToLogin(event)) return;", limits)
        for exported in (
            "loginRequiredForHandle,",
            "loginRequiredForCart,",
            "loginRequiredForCartForm,",
            "loginRedirectUrl,",
            "redirectToLogin,",
        ):
            with self.subTest(exported=exported):
                self.assertIn(exported, limits)

    def test_redirect_is_scoped_to_the_limited_product_being_purchased(self) -> None:
        limits = self.read("assets/customer-order-limits.js")
        product = self.read("assets/product-form.js")

        # Add to Cart and Buy Now look only at the product in hand: an unrelated
        # limited product sitting in the cart must not divert other purchases.
        self.assertNotIn("loginRequiredForHandle(handle) || loginRequiredForCart()", limits)
        self.assertNotIn("loginRequiredForCart", product)
        self.assertNotIn("redirectToLogin", product)
        # Cart-wide checks stay on the cart form, where the limited line is
        # real: one click guard and one submit guard, nowhere else.
        self.assertEqual(limits.count("loginRequiredForCartForm("), 2)

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

    def test_purchase_surfaces_send_proven_guests_to_login(self) -> None:
        limits = self.read("assets/customer-order-limits.js")
        listing = self.read("assets/product-card-cart-feedback.js")
        buy_now = self.read("assets/buy-now-limit-checkout.js")
        cart = self.read("assets/cart.js")

        self.assertIn("/account/login?redirect_uri=${encodeURIComponent(target)}", limits)
        self.assertIn("window.location.assign(loginRedirectUrl())", limits)
        self.assertEqual(limits.count("sendToLogin(event)"), 5)

        self.assertIn(
            "&& limits.loginRequiredForHandle(this.button.dataset.productHandle)\n"
            "        && limits.redirectToLogin()",
            listing,
        )
        self.assertIn(
            "&& limits.loginRequiredForHandle(productHandle(form))\n"
            "      && limits.redirectToLogin()",
            buy_now,
        )
        self.assertIn(
            "if (api.loginRequiredForCartForm(form) && api.redirectToLogin()) {",
            cart,
        )

    def test_limit_copy_no_longer_targets_guests(self) -> None:
        copy = self.read("assets/customer-order-limit-copy.js")

        self.assertNotIn("loginRequired", copy)
        self.assertNotIn("Sign in to purchase", copy)
        self.assertIn(
            "const customerLimitReached = remaining != null && remaining <= 0;",
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
