from __future__ import annotations

import re
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
THEME_ROOT = REPOSITORY_ROOT / "theme"
PRODUCT_CARD = THEME_ROOT / "snippets" / "product-card.liquid"
STOREFRONT_CART_CONTROLS_CSS = (
    THEME_ROOT / "assets" / "component-product-card-cart-controls.css"
)
EDITOR_CART_CONTROLS_CSS = (
    THEME_ROOT / "editor_assets" / "component-product-card-cart-controls.css"
)


class ProductListingSaleOverlayTests(unittest.TestCase):
    def test_sale_state_markup_is_preserved_but_explicitly_hidden(self) -> None:
        product_card = PRODUCT_CARD.read_text(encoding="utf-8")

        self.assertIn("{% assign on_sale = false %}", product_card)
        self.assertIn("{% assign sale_text", product_card)
        self.assertIn("{% if on_sale %}", product_card)
        self.assertRegex(
            product_card,
            re.compile(
                r'<div\s+class="card__badge card__badge-on_sale card__badge-top-left"'
                r'\s+hidden="hidden"\s+aria-hidden="true">'
            ),
        )

    def test_every_listing_sale_badge_is_hidden_at_the_markup_source(self) -> None:
        sale_badge_files = []
        for liquid_file in THEME_ROOT.rglob("*.liquid"):
            content = liquid_file.read_text(encoding="utf-8")
            if "card__badge-on_sale" in content:
                sale_badge_files.append(liquid_file.relative_to(REPOSITORY_ROOT).as_posix())
                self.assertIn('hidden="hidden"', content)

        self.assertEqual(sale_badge_files, ["theme/snippets/product-card.liquid"])

    def test_visibility_does_not_depend_on_optional_cart_control_css(self) -> None:
        storefront_css = STOREFRONT_CART_CONTROLS_CSS.read_text(encoding="utf-8")
        editor_css = EDITOR_CART_CONTROLS_CSS.read_text(encoding="utf-8")

        self.assertEqual(storefront_css, editor_css)
        self.assertNotIn("card__badge-on_sale", storefront_css)

    def test_sold_out_badges_and_sale_pricing_remain_available(self) -> None:
        product_card = PRODUCT_CARD.read_text(encoding="utf-8")

        self.assertIn("card__badge-sold_out", product_card)
        self.assertIn("{% if sold_out %}", product_card)
        self.assertIn("{% include 'price' %}", product_card)


if __name__ == "__main__":
    unittest.main()