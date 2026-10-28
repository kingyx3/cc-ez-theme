"""Regression guardrails for avoiding unused assets on public storefront pages."""
from __future__ import annotations

import unittest
from pathlib import Path


THEME = Path(__file__).resolve().parents[2] / "theme"


def read(relative_path: str) -> str:
    return (THEME / relative_path).read_text(encoding="utf-8")


class StorefrontAssetBudgetTests(unittest.TestCase):
    def test_listing_cart_assets_follow_the_same_global_toggle_as_the_button(self) -> None:
        card = read("snippets/product-card.liquid")
        toggle = "{% if show_listing_add_to_cart %}"
        asset_guard = "{% unless product_card_cart_controls_assets_loaded %}"
        css = "component-product-card-cart-controls.css"
        js = "product-card-cart-feedback.js"
        button = "<add-to-cart-button>"

        self.assertIn("settings.show_add_to_cart_button == false", card)
        self.assertIn("settings.show_add_to_cart_button == 0", card)
        self.assertIn("settings.show_add_to_cart_button == '0'", card)
        self.assertEqual(card.count("{% assign show_listing_add_to_cart = true %}"), 1)
        self.assertEqual(card.count(toggle), 2)
        self.assertLess(card.index(toggle), card.index(asset_guard))
        self.assertLess(card.index(asset_guard), card.index(css))
        self.assertLess(card.index(css), card.index(js))
        self.assertLess(card.index(js), card.index(button))
        # One set of asset tags per page even with many product cards.
        self.assertEqual(card.count(css), 1)
        self.assertEqual(card.count(js), 1)

    def test_account_details_validation_is_not_loaded_on_public_templates(self) -> None:
        layout = read("layout/theme.liquid")
        script = "account-details-validation.js"
        guard = "{% if template contains 'customers' %}"
        self.assertEqual(layout.count(script), 1)
        self.assertIn(guard, layout)
        self.assertLess(layout.index(guard), layout.index(script))
        self.assertIn("{% endif %}", layout[layout.index(script):layout.index(script) + 150])

    def test_grid_images_decode_without_blocking_the_main_thread(self) -> None:
        card = read("snippets/product-card.liquid")
        main = card.split('srcset="{{ product.featured_image.src', 1)[1].split(">", 1)[0]
        self.assertIn('decoding="async"', main)
        self.assertIn('loading="eager"', main)
        self.assertIn('loading="lazy"', main)
        self.assertIn('fetchpriority="high"', main)


if __name__ == "__main__":
    unittest.main()
