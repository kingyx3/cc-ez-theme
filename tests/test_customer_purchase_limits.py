from __future__ import annotations

import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
THEME_ROOT = REPOSITORY_ROOT / "theme"
SNIPPET = THEME_ROOT / "snippets" / "customer-purchase-limits.liquid"
CURRENCIES = THEME_ROOT / "snippets" / "currencies.liquid"
CART_ITEM = THEME_ROOT / "snippets" / "cart-item.liquid"
STOREFRONT_HELPER = THEME_ROOT / "assets" / "customer-purchase-limits.js"
EDITOR_HELPER = THEME_ROOT / "editor_assets" / "customer-purchase-limits.js"


class CustomerPurchaseLimitsTests(unittest.TestCase):
    def test_disabled_configuration_is_a_true_no_op(self) -> None:
        snippet = SNIPPET.read_text(encoding="utf-8")
        currencies = CURRENCIES.read_text(encoding="utf-8")

        self.assertIn("{% assign customer_purchase_limit_rules = '' %}", snippet)
        self.assertIn(
            "{% if customer_purchase_limit_rules_source != blank %}",
            snippet,
        )
        self.assertIn("customer-purchase-limits.js", snippet)
        self.assertIn('defer="defer"', snippet)
        self.assertIn("{% include 'customer-purchase-limits' %}", currencies)
        self.assertNotIn("customer-purchase-limits.js", currencies)
        self.assertLess(
            snippet.index("{% if customer_purchase_limit_rules_source != blank %}"),
            snippet.index("<script>"),
        )

    def test_order_history_and_private_refresh_calculation_remain_server_side(self) -> None:
        snippet = SNIPPET.read_text(encoding="utf-8")

        self.assertIn("customer.orders", snippet)
        self.assertIn("order.line_items", snippet)
        self.assertIn("line_item.product.handle", snippet)
        self.assertIn("order.is_cancelled", snippet)
        self.assertIn("active_refresh_epoch", snippet)
        self.assertIn("limit: 20", snippet)
        self.assertNotIn("activeRefreshDate", snippet)
        self.assertNotIn("nextRefreshDate", snippet)
        self.assertNotIn("next_refresh_date", snippet)
        self.assertIn("products[product_handle]", snippet)
        self.assertIn("variantHandles", snippet)

    def test_runtime_is_a_pure_helper_without_inferred_success(self) -> None:
        storefront = STOREFRONT_HELPER.read_text(encoding="utf-8")
        editor = EDITOR_HELPER.read_text(encoding="utf-8")

        self.assertEqual(storefront, editor)
        self.assertIn("if (!source || source.enabled !== true", storefront)
        self.assertIn("const quantityLimitForVariant", storefront)
        self.assertIn("const additionViolation", storefront)
        self.assertIn("const cartViolationFromForm", storefront)
        self.assertIn("const recordAdditionForVariant", storefront)
        self.assertIn("const recordRemovalForVariant", storefront)
        self.assertIn("const syncCartFromForm", storefront)
        self.assertNotIn("EasyStore.Action", storefront)
        self.assertNotIn(".prototype", storefront)
        self.assertNotIn("callbackError", storefront)
        self.assertNotIn("pendingAdds", storefront)
        self.assertNotIn("queueAdditionCandidate", storefront)
        self.assertNotIn("MutationObserver", storefront)
        self.assertNotIn("nextRefreshDate", storefront)
        self.assertNotIn("Entitlement refreshes", storefront)

    def test_native_components_own_checks_and_success_reconciliation(self) -> None:
        product_form = (THEME_ROOT / "assets" / "product-form.js").read_text(
            encoding="utf-8"
        )
        product_form_editor = (
            THEME_ROOT / "editor_assets" / "product-form.js"
        ).read_text(encoding="utf-8")
        listing = (
            THEME_ROOT / "assets" / "product-card-cart-feedback.js"
        ).read_text(encoding="utf-8")
        listing_editor = (
            THEME_ROOT / "editor_assets" / "product-card-cart-feedback.js"
        ).read_text(encoding="utf-8")
        cart = (THEME_ROOT / "assets" / "cart.js").read_text(encoding="utf-8")
        cart_editor = (
            THEME_ROOT / "editor_assets" / "cart.js"
        ).read_text(encoding="utf-8")

        self.assertEqual(product_form, product_form_editor)
        self.assertEqual(listing, listing_editor)
        self.assertEqual(cart, cart_editor)

        self.assertIn("quantityLimitForVariant", product_form)
        self.assertIn("recordAdditionForVariant", product_form)
        self.assertIn("additionViolation(productHandle", listing)
        self.assertIn("recordAddition(productHandle", listing)
        self.assertIn("cartViolationFromForm", cart)
        self.assertIn("allowDecreases: true", cart)
        self.assertIn("customerLimitPreviousValue", cart)
        self.assertIn("syncCartFromForm", cart)
        self.assertIn("recordRemovalForVariant", cart)
        self.assertIn("document.addEventListener('submit'", cart)
        self.assertIn("EasyStore.Action.addToCart", product_form)
        self.assertIn("EasyStore.Action.updateCart", cart)
        self.assertIn("EasyStore.Action.removeCartItem", cart)

    def test_cart_form_serializes_product_handles_for_combined_limits(self) -> None:
        cart_item = CART_ITEM.read_text(encoding="utf-8")
        helper = STOREFRONT_HELPER.read_text(encoding="utf-8")

        self.assertIn('name="product_handles[]"', cart_item)
        self.assertIn("arrayValue(body, 'product_handles')", helper)
        self.assertIn("handleQuantities[handle]", helper)


if __name__ == "__main__":
    unittest.main()
