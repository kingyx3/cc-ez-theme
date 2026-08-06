from __future__ import annotations

import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
THEME_ROOT = REPOSITORY_ROOT / "theme"
SNIPPET = THEME_ROOT / "snippets" / "customer-purchase-limits.liquid"
CURRENCIES = THEME_ROOT / "snippets" / "currencies.liquid"
STOREFRONT_JS = THEME_ROOT / "assets" / "customer-purchase-limits.js"
EDITOR_JS = THEME_ROOT / "editor_assets" / "customer-purchase-limits.js"


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
        self.assertIn("defer=\"defer\"", snippet)
        self.assertIn("{% include 'customer-purchase-limits' %}", currencies)
        self.assertNotIn("customer-purchase-limits.js", currencies)

        first_condition = snippet.index(
            "{% if customer_purchase_limit_rules_source != blank %}"
        )
        first_runtime_script = snippet.index("<script>")
        asset_script = snippet.index("customer-purchase-limits.js")
        self.assertLess(first_condition, first_runtime_script)
        self.assertLess(first_condition, asset_script)

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

    def test_runtime_uses_event_guards_without_global_monkey_patching(self) -> None:
        storefront = STOREFRONT_JS.read_text(encoding="utf-8")
        editor = EDITOR_JS.read_text(encoding="utf-8")

        self.assertEqual(storefront, editor)
        self.assertIn("if (!source || source.enabled !== true", storefront)
        self.assertIn("document.addEventListener('click'", storefront)
        self.assertIn("document.addEventListener('submit'", storefront)
        self.assertIn("document.addEventListener('change'", storefront)
        self.assertIn("const additionViolation", storefront)
        self.assertIn("const cartViolation", storefront)
        self.assertIn("allowDecreases", storefront)
        self.assertIn("customerLimitPreviousValue", storefront)
        self.assertIn("queueAdditionCandidate", storefront)
        self.assertIn("MutationObserver", storefront)
        self.assertNotIn("EasyStore.Action", storefront)
        self.assertNotIn(".prototype", storefront)
        self.assertNotIn("customElements.get", storefront)
        self.assertNotIn("callbackError", storefront)
        self.assertNotIn("nextRefreshDate", storefront)
        self.assertNotIn("Entitlement refreshes", storefront)

    def test_theme_surfaces_use_server_rendered_handle_mapping(self) -> None:
        snippet = SNIPPET.read_text(encoding="utf-8")
        storefront = STOREFRONT_JS.read_text(encoding="utf-8")
        product_card = (
            THEME_ROOT / "snippets" / "product-card.liquid"
        ).read_text(encoding="utf-8")

        self.assertIn("window.customerPurchaseLimits.variantHandles", snippet)
        self.assertIn("limited_product.variants", snippet)
        self.assertIn("const handleForVariant", storefront)
        self.assertIn("const handleForProductForm", storefront)
        self.assertIn("readCartFromDom", storefront)
        self.assertIn('#cart-form [name="ids[]"]', storefront)
        self.assertIn('data-product-handle="{{product.handle}}"', product_card)

    def test_adjacent_native_behaviors_are_not_removed(self) -> None:
        product_form = (
            THEME_ROOT / "assets" / "product-form.js"
        ).read_text(encoding="utf-8")
        cart = (THEME_ROOT / "assets" / "cart.js").read_text(encoding="utf-8")
        global_js = (
            THEME_ROOT / "assets" / "global.js"
        ).read_text(encoding="utf-8")

        self.assertIn("EasyStore.Action.addToCart", product_form)
        self.assertIn("EasyStore.Action.updateCart", cart)
        self.assertIn("EasyStore.Action.removeCartItem", cart)
        self.assertIn("customElements.define('add-to-cart-button'", global_js)


if __name__ == "__main__":
    unittest.main()