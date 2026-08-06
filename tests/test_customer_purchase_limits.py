from __future__ import annotations

import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
THEME_ROOT = REPOSITORY_ROOT / "theme"


class CustomerPurchaseLimitRollbackTests(unittest.TestCase):
    def test_pr56_runtime_files_are_removed(self) -> None:
        removed_paths = (
            THEME_ROOT / "assets" / "customer-purchase-limits.js",
            THEME_ROOT / "editor_assets" / "customer-purchase-limits.js",
            THEME_ROOT / "snippets" / "customer-purchase-limits.liquid",
        )

        for path in removed_paths:
            with self.subTest(path=path.relative_to(REPOSITORY_ROOT)):
                self.assertFalse(path.exists())

    def test_global_currency_loader_matches_pre_pr56_behavior(self) -> None:
        currencies = (
            THEME_ROOT / "snippets" / "currencies.liquid"
        ).read_text(encoding="utf-8")

        self.assertNotIn("customer-purchase-limits", currencies)
        self.assertNotIn("customerPurchaseLimits", currencies)
        self.assertIn("purchase-limit-feedback.js", currencies)
        self.assertIn("window.purchaseCartQuantities", currencies)
        self.assertIn("EasyStore.Currencies.init", currencies)

    def test_custom_across_order_identifiers_are_absent_from_runtime(self) -> None:
        forbidden = (
            "customer-purchase-limits",
            "customerPurchaseLimits",
            "customerPurchaseLimitVariantHandles",
            "purchaseCartHandleQuantities",
            "purchaseCartLines",
            "recordAdditionForVariant",
            "recordRemovalForVariant",
            "cartViolationFromForm",
            "customerLimitPreviousValue",
            'name="product_handles[]"',
        )

        runtime_files = [
            path
            for path in THEME_ROOT.rglob("*")
            if path.is_file() and path.suffix in {".js", ".liquid"}
        ]
        for path in runtime_files:
            content = path.read_text(encoding="utf-8")
            for identifier in forbidden:
                with self.subTest(
                    path=path.relative_to(REPOSITORY_ROOT),
                    identifier=identifier,
                ):
                    self.assertNotIn(identifier, content)

    def test_native_commerce_paths_remain_intact_and_mirrored(self) -> None:
        mirrored_assets = (
            "cart.js",
            "product-card-cart-feedback.js",
            "product-form.js",
        )
        for filename in mirrored_assets:
            storefront = (THEME_ROOT / "assets" / filename).read_text(
                encoding="utf-8"
            )
            editor = (THEME_ROOT / "editor_assets" / filename).read_text(
                encoding="utf-8"
            )
            with self.subTest(filename=filename):
                self.assertEqual(storefront, editor)

        cart = (THEME_ROOT / "assets" / "cart.js").read_text(encoding="utf-8")
        listing = (
            THEME_ROOT / "assets" / "product-card-cart-feedback.js"
        ).read_text(encoding="utf-8")
        product_form = (
            THEME_ROOT / "assets" / "product-form.js"
        ).read_text(encoding="utf-8")

        self.assertIn("EasyStore.Action.updateCart", cart)
        self.assertIn("EasyStore.Action.removeCartItem", cart)
        self.assertIn("EasyStore.Action.addToCart", listing)
        self.assertIn("EasyStore.Action.addToCart", product_form)


if __name__ == "__main__":
    unittest.main()
