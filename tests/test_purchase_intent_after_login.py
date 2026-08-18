"""A purchase attempt has to survive the trip through EasyStore's login.

A guest who presses Buy Now on a limited product is sent to sign in, and the
click is lost on the way. The shopper comes back to the product page, and if
their allowance was already spent on previous orders the page said nothing
about it: the button looked ready and only a second press produced "Customer
purchase limit reached". The attempt is now recorded when the shopper is sent
away and answered when they return.

`e2e/purchase-limit-after-login.spec.js` drives the real module through real
page loads for every surface. What is asserted here is what behaviour cannot
see: that every surface that redirects also names what was being bought, and
that the answer is confined to a shopper whose allowance can be measured.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
THEME_ROOT = REPOSITORY_ROOT / "theme"

# Add to Cart, Buy Now, listing quick-add, and the cart's own checkout controls.
SURFACES = ("product", "buy-now", "listing", "cart")


def code_only(source: str) -> str:
    """Strip comments so assertions describe behaviour, not prose."""
    without_blocks = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return "\n".join(
        line for line in without_blocks.splitlines()
        if not line.strip().startswith("//")
    )


def read(relative: str) -> str:
    return (THEME_ROOT / relative).read_text(encoding="utf-8")


class EverySurfaceRecordsWhatWasBeingBoughtTests(unittest.TestCase):
    def test_the_redirect_helpers_carry_the_attempt(self) -> None:
        limits = code_only(read("assets/customer-order-limits.js"))

        self.assertIn("const redirectToLogin = (intent = null) => {", limits)
        self.assertIn("rememberPurchaseIntent(intent);", limits)
        self.assertIn("const sendToLogin = (event, intent = null) => {", limits)
        self.assertIn("return redirectToLogin(intent);", limits)

    def test_each_guard_names_its_own_surface(self) -> None:
        limits = code_only(read("assets/customer-order-limits.js"))

        # One per delegated guard: listing quick-add, Buy Now, cart checkout
        # click, Add to Cart submit, cart checkout submit.
        self.assertEqual(limits.count("sendToLogin(event, "), 5)
        for surface in SURFACES:
            with self.subTest(surface=surface):
                self.assertIn(f"surface: '{surface}'", limits)

    def test_the_components_that_redirect_do_the_same(self) -> None:
        listing = code_only(read("assets/product-card-cart-feedback.js"))
        buy_now = code_only(read("assets/buy-now-limit-checkout.js"))
        cart = code_only(read("assets/cart.js"))

        self.assertIn("handle: this.button.dataset.productHandle,", listing)
        self.assertIn("surface: 'listing',", listing)
        self.assertIn("handle: productHandle(form),", buy_now)
        self.assertIn("surface: 'buy-now',", buy_now)
        self.assertIn("api.redirectToLogin({ surface: 'cart' })", cart)

    def test_a_quantity_is_recorded_alongside_the_product(self) -> None:
        limits = code_only(read("assets/customer-order-limits.js"))

        # "You can add up to 1 more" and "limit reached" are different answers,
        # and which one applies depends on how many units were asked for.
        self.assertIn("quantity: listingButton.dataset.quantity,", limits)
        self.assertEqual(
            limits.count("quantity: form?.querySelector('[name=\"quantity\"]')?.value,")
            + limits.count("quantity: form.querySelector('[name=\"quantity\"]')?.value,"),
            2,
        )


class TheAttemptIsAnsweredOnlyWhereItAppliesTests(unittest.TestCase):
    def test_only_a_shopper_proven_signed_in_is_answered(self) -> None:
        limits = code_only(read("assets/customer-order-limits.js"))

        # Proof of signing in, not the mere absence of proof of signing out: an
        # allowance can only be measured for a customer.
        self.assertIn(
            "const shopperSignedIn = () => (\n"
            "    customerAuthenticated || Boolean(document.querySelector(SIGNED_IN_MARKUP))\n"
            "  );",
            limits,
        )
        # An account page is where EasyStore lands them and a step still on the
        # page means the sign-in is not finished, so neither answers an attempt.
        self.assertIn("if (stillAuthenticating() || !shopperSignedIn()) return;", limits)
        self.assertIn(
            "  const stillAuthenticating = () => (\n"
            "    onAccountPage() || Boolean(document.querySelector(AUTHENTICATING_MARKUP))\n"
            "  );",
            limits,
        )

    def test_the_answer_waits_for_history_instead_of_assuming_none(self) -> None:
        limits = code_only(read("assets/customer-order-limits.js"))

        self.assertIn(
            "    const waiting = intent.surface === 'cart'\n"
            "      ? historyBlocksCart()\n"
            "      : historyBlocks(intent.handle);",
            limits,
        )
        # Both endings of a load are listened for, so a failed one still answers
        # rather than leaving the shopper waiting for a message that never comes.
        self.assertIn("document.addEventListener('customer-order-limits:history', answer);", limits)
        self.assertIn(
            "document.addEventListener('customer-order-limits:history-unavailable', answer);",
            limits,
        )
        self.assertIn("document.removeEventListener('customer-order-limits:history', answer);", limits)

    def test_the_attempt_is_consumed_once_and_expires(self) -> None:
        limits = code_only(read("assets/customer-order-limits.js"))

        self.assertIn("const INTENT_KEY = 'cc:pending-purchase-intent';", limits)
        self.assertIn("const INTENT_MAX_AGE_MS = 1800000;", limits)
        self.assertIn("window.sessionStorage.removeItem(INTENT_KEY);", limits)
        self.assertIn(
            "if (!storedAt || storedAt + INTENT_MAX_AGE_MS < nowMs()) return null;",
            limits,
        )

    def test_buy_now_at_the_limit_with_a_full_cart_says_nothing(self) -> None:
        limits = code_only(read("assets/customer-order-limits.js"))

        # The button checks out with what the cart holds in that case, so an
        # error message would contradict what pressing it actually does.
        self.assertIn(
            "    if (\n"
            "      intent.surface === 'buy-now'\n"
            "      && violation.remaining <= 0\n"
            "      && cartQuantityForHandle(intent.handle) > 0\n"
            "    ) return null;",
            limits,
        )

    def test_the_message_lands_on_the_surface_the_click_came_from(self) -> None:
        limits = code_only(read("assets/customer-order-limits.js"))

        # The same three renderers a click uses, so a replayed attempt reads
        # exactly like the attempt itself.
        self.assertIn("if (violation) showCartError(violation.message);", limits)
        self.assertIn("if (form) showProductError(form, violation.message);", limits)
        self.assertIn("else showListingError(violation.message);", limits)

    def test_the_answer_runs_after_the_history_load_is_started(self) -> None:
        limits = read("assets/customer-order-limits.js")

        # Ordering matters: a cached history is applied by that block, so the
        # answer either has the real numbers or knows to wait for them.
        self.assertIn(
            "    else historyState = 'unavailable';\n"
            "  }\n\n"
            "  applyPurchaseIntent();\n"
            "})();",
            limits,
        )


if __name__ == "__main__":
    unittest.main()
