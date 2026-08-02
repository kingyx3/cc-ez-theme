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
        self.assertIn("Stock limit reached.", storefront)
        self.assertIn("Purchase limit reached.", storefront)
        self.assertIn("Quantity limit exceeded.", storefront)
        self.assertIn("Maximum quantity reached.", storefront)
        self.assertIn("You can add up to", storefront)
        self.assertIn("Math.max(0, totalMaximum - currentQuantity)", storefront)
        self.assertNotIn("would bring your cart to", storefront)
        self.assertNotIn("Remove an item before adding more.", storefront)

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
        self.assertIn("content.textContent = format", helper)
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
