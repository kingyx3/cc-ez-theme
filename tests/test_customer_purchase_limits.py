from __future__ import annotations

import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
THEME_ROOT = REPOSITORY_ROOT / "theme"


class CustomerPurchaseLimitsTests(unittest.TestCase):
    def test_handle_based_limit_configuration_is_loaded(self) -> None:
        snippet = (
            THEME_ROOT / "snippets" / "customer-purchase-limits.liquid"
        ).read_text(encoding="utf-8")
        currencies = (
            THEME_ROOT / "snippets" / "currencies.liquid"
        ).read_text(encoding="utf-8")

        self.assertIn("customer_purchase_limit_rules", snippet)
        self.assertIn("product-handle|maximum-units", snippet)
        self.assertIn("customer.orders", snippet)
        self.assertIn("order.line_items", snippet)
        self.assertIn("line_item.product.handle", snippet)
        self.assertIn("order.is_cancelled", snippet)
        self.assertIn("active_refresh_epoch", snippet)
        self.assertIn("next_refresh_date", snippet)
        self.assertIn("window.customerPurchaseLimits.rules", snippet)
        self.assertIn("window.customerPurchaseLimitVariantHandles", snippet)
        self.assertIn("window.purchaseCartHandleQuantities", snippet)
        self.assertIn("window.purchaseCartLines", snippet)
        self.assertIn(
            "{% include 'customer-purchase-limits' %}",
            currencies,
        )
        self.assertIn("customer-purchase-limits.js", currencies)

    def test_customer_limits_cover_product_and_cart_actions(self) -> None:
        storefront = (
            THEME_ROOT / "assets" / "customer-purchase-limits.js"
        ).read_text(encoding="utf-8")
        editor = (
            THEME_ROOT / "editor_assets" / "customer-purchase-limits.js"
        ).read_text(encoding="utf-8")

        self.assertEqual(storefront, editor)
        self.assertIn("const customerLimitForVariant", storefront)
        self.assertIn("const blockedAddition", storefront)
        self.assertIn("Purchase limits are tracked across customer orders", storefront)
        self.assertIn("Entitlement refreshes on", storefront)
        self.assertIn("action.addToCart = enhancedAddToCart", storefront)
        self.assertIn("action.updateCart = enhancedUpdateCart", storefront)
        self.assertIn("action.removeCartItem = enhancedRemoveCartItem", storefront)
        self.assertIn("const isCheckoutForm = form.id === 'cart-form'", storefront)
        self.assertIn("const violation = cartViolation(cartHandles())", storefront)
        self.assertIn("content.textContent = message", storefront)


if __name__ == "__main__":
    unittest.main()
