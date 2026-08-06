from __future__ import annotations

import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PRODUCT_CARD = REPOSITORY_ROOT / "theme" / "snippets" / "product-card.liquid"


class ProductListingSaleOverlayTests(unittest.TestCase):
    def test_shared_product_cards_do_not_render_sale_photo_overlays(self) -> None:
        product_card = PRODUCT_CARD.read_text(encoding="utf-8")

        self.assertNotIn("card__badge-on_sale", product_card)
        self.assertNotIn("{% if on_sale %}", product_card)
        self.assertNotIn("{% assign sale_text", product_card)
        self.assertNotIn("{% assign on_sale", product_card)

    def test_sold_out_badges_and_sale_pricing_remain_available(self) -> None:
        product_card = PRODUCT_CARD.read_text(encoding="utf-8")

        self.assertIn("card__badge-sold_out", product_card)
        self.assertIn("{% if sold_out %}", product_card)
        self.assertIn("{% include 'price' %}", product_card)


if __name__ == "__main__":
    unittest.main()
