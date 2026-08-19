from __future__ import annotations

import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
THEME_ROOT = REPOSITORY_ROOT / "theme"


class ContextualPurchaseLimitFeedbackTests(unittest.TestCase):
    def test_purchase_limit_helper_is_loaded_with_variant_cart_quantities(self) -> None:
        currencies = (THEME_ROOT / "snippets" / "currencies.liquid").read_text(
            encoding="utf-8"
        )

        self.assertIn("window.purchaseCartQuantities = {};", currencies)
        self.assertIn("{% for item in cart.items %}", currencies)
        self.assertIn("item.variant_id", currencies)
        self.assertIn("item.quantity", currencies)
        self.assertIn("purchase-limit-feedback.js", currencies)

    def test_storefront_and_editor_helpers_match(self) -> None:
        storefront = (
            THEME_ROOT / "assets" / "purchase-limit-feedback.js"
        ).read_text(encoding="utf-8")
        editor = (
            THEME_ROOT / "editor_assets" / "purchase-limit-feedback.js"
        ).read_text(encoding="utf-8")

        self.assertEqual(storefront, editor)
        self.assertIn("const stripMarkup", storefront)
        self.assertIn("container.innerHTML", storefront)
        self.assertIn("container.textContent", storefront)
        self.assertIn("const extractMaximum", storefront)
        self.assertIn("only\\s+(?:has\\s+)?(?:left\\s+)?", storefront)
        self.assertIn("Limit reached: ${limit.clause}.", storefront)
        self.assertIn("Maximum ${unitLabel(remaining)} (${limit.short}).", storefront)
        self.assertIn("This item cannot be added right now.", storefront)
        self.assertNotIn("You can add", storefront)
        self.assertIn("Math.max(0, totalMaximum - currentQuantity)", storefront)
        self.assertNotIn("would bring your cart to", storefront)
        self.assertNotIn("Remove an item before adding more.", storefront)

    def test_limit_copy_states_the_ceiling_instead_of_an_equation(self) -> None:
        # "2 units in cart + 2 units selected = 0 units maximum" read as broken
        # arithmetic and quoted the remaining allowance as though it were the
        # limit. Copy now names the ceiling as a short phrase.
        storefront = (
            THEME_ROOT / "assets" / "purchase-limit-feedback.js"
        ).read_text(encoding="utf-8")

        # One ceiling, three sentence positions, spelled out together per reason:
        # after "Limit reached:", inside a parenthetical, and on its own.
        self.assertIn("const ceiling = (reason, maximum) => {", storefront)
        self.assertIn("${unitLabel(maximum)} per customer", storefront)
        self.assertIn("only ${unitLabel(maximum)} in stock", storefront)
        self.assertIn("sentence: `Maximum ${unitLabel(maximum)} per customer.`", storefront)
        self.assertIn("sentence: `Only ${unitLabel(maximum)} left.`", storefront)
        self.assertIn(
            "Limit reached: ${limit.clause}. You have ${current} in your cart.",
            storefront,
        )
        # One lead, one clause. The copy this replaced restated the ceiling in a
        # second sentence of its own after already naming it.
        self.assertNotIn("the limit is ${", storefront)
        self.assertNotIn("cannot add more of this item.", storefront)
        self.assertNotIn("in cart +", storefront)
        self.assertNotIn("selected = ${", storefront)
        self.assertNotIn("units maximum", storefront)
        self.assertNotIn("(maximum ${maximumCopy})", storefront)

    def test_a_limit_that_measured_the_cart_is_not_discounted_twice(self) -> None:
        # The customer order limit reports what is still addable, so subtracting
        # the cart from it again both double counted the cart and left the copy
        # quoting nothing-left as the maximum.
        storefront = (
            THEME_ROOT / "assets" / "purchase-limit-feedback.js"
        ).read_text(encoding="utf-8")

        self.assertIn("if (limit.contextual === true) {", storefront)
        self.assertIn("const limitMessage = (limit, context) => (", storefront)
        self.assertIn("limit && limit.contextual === true && limit.message", storefront)
        self.assertIn("limitMessage(limit, { ...context, mode: 'error' })", storefront)

    def test_reason_detection_reads_the_supplied_limit_label(self) -> None:
        # The plus button raises a limit from live numbers with no message, so
        # judging the reason on the message alone always fell through to the
        # generic wording.
        storefront = (
            THEME_ROOT / "assets" / "purchase-limit-feedback.js"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "const text = `${stripMarkup(value)} ${stripMarkup(fallbackLabel)}`",
            storefront,
        )
        self.assertIn("\\d+\\s+unit(?:s|\\(s\\))?\\s+left", storefront)

    def test_product_forms_only_show_feedback_after_a_blocked_action(self) -> None:
        helper = (
            THEME_ROOT / "assets" / "purchase-limit-feedback.js"
        ).read_text(encoding="utf-8")

        self.assertIn("customElements.whenDefined('product-form')", helper)
        self.assertIn("prototype.bindPurchaseLimitInteraction", helper)
        self.assertIn("prototype.getQuantityLimit", helper)
        self.assertIn("prototype.validateQuantity", helper)
        self.assertIn("prototype.rememberRejectedQuantity", helper)
        self.assertIn("prototype.openBuyNowLimitModal", helper)
        self.assertIn("prototype.renderErrorMsg", helper)
        self.assertIn("purchaseLimitFeedbackBound", helper)
        self.assertIn("mode: 'reached'", helper)
        self.assertIn("const shouldShow = focusInvalid", helper)
        self.assertIn("this.purchaseLimitInteracted === true", helper)
        # The alert still renders the formatted message, but only for a form
        # that has no quantity note to put it in.
        self.assertIn("const text = format({ ...context, rawMessage: cleanMessage });", helper)
        self.assertIn("content.textContent = text;", helper)
        self.assertIn("this.showQuantityLimit(", helper)
        self.assertIn("this.clearQuantityLimit();", helper)
        self.assertNotIn("quantity === limit.maximum", helper)
        self.assertNotIn("mode === 'warning'", helper)
        self.assertNotIn("content.innerHTML = message", helper)

    def test_listing_alerts_use_the_shared_contextual_formatter(self) -> None:
        scripts = []
        for directory in ("assets", "editor_assets"):
            script = (
                THEME_ROOT / directory / "product-card-cart-feedback.js"
            ).read_text(encoding="utf-8")
            scripts.append(script)

            self.assertIn("window.PurchaseLimitFeedback", script)
            self.assertIn("feedback.getCartQuantity(variantId)", script)
            self.assertIn("feedback.format", script)
            self.assertIn("currentQuantity", script)
            self.assertIn("requestedQuantity", script)
            self.assertIn("messageElement.textContent", script)
            self.assertNotIn("messageElement.innerHTML", script)

        self.assertEqual(scripts[0], scripts[1])


if __name__ == "__main__":
    unittest.main()
