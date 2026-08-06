from __future__ import annotations

import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PRODUCT_CARD = REPOSITORY_ROOT / "theme" / "snippets" / "product-card.liquid"
STOREFRONT_CSS = (
    REPOSITORY_ROOT
    / "theme"
    / "assets"
    / "component-product-card-cart-controls.css"
)
EDITOR_CSS = (
    REPOSITORY_ROOT
    / "theme"
    / "editor_assets"
    / "component-product-card-cart-controls.css"
)


class ProductListingSaleOverlayTests(unittest.TestCase):
    def test_sale_state_markup_is_preserved_for_theme_compatibility(self) -> None:
        product_card = PRODUCT_CARD.read_text(encoding="utf-8")

        self.assertIn("{% assign on_sale = false %}", product_card)
        self.assertIn("{% assign sale_text", product_card)
        self.assertIn("{% if on_sale %}", product_card)
        self.assertIn("card__badge-on_sale", product_card)

    def test_listing_sale_overlay_is_hidden_by_mirrored_css(self) -> None:
        storefront_css = STOREFRONT_CSS.read_text(encoding="utf-8")
        editor_css = EDITOR_CSS.read_text(encoding="utf-8")

        self.assertEqual(storefront_css, editor_css)
        self.assertIn(".product-card-wrapper .card__badge-on_sale", storefront_css)
        self.assertIn("display: none;", storefront_css)

    def test_sold_out_badges_and_sale_pricing_remain_available(self) -> None:
        product_card = PRODUCT_CARD.read_text(encoding="utf-8")

        self.assertIn("card__badge-sold_out", product_card)
        self.assertIn("{% if sold_out %}", product_card)
        self.assertIn("{% include 'price' %}", product_card)


if __name__ == "__main__":
    unittest.main()
