"""Guard lazy loading for offscreen YouTube videos in product media carousels."""
from __future__ import annotations

import unittest
from pathlib import Path


THEME = Path(__file__).resolve().parents[2] / "theme"


class ProductVideoDeliveryTests(unittest.TestCase):
    def test_product_primary_video_is_eager_and_later_video_is_lazy(self) -> None:
        source = (THEME / "sections" / "main-product.liquid").read_text(
            encoding="utf-8"
        )
        self.assertIn('src="https://www.youtube.com/embed/{{ image.id }}"', source)
        self.assertIn(
            '{% if forloop.first %}loading="eager"{% else %}loading="lazy"{% endif %} allowfullscreen',
            source,
        )

    def test_featured_product_preserves_the_visible_first_video(self) -> None:
        source = (THEME / "sections" / "featured-product.liquid").read_text(
            encoding="utf-8"
        )
        self.assertIn("{% assign has_selected_featured_media = false %}", source)
        self.assertIn("{% assign has_selected_featured_media = true %}", source)
        self.assertIn(
            '{% if has_selected_featured_media or forloop.index > 1 %}loading="lazy"{% endif %} allowfullscreen',
            source,
        )
        self.assertIn('src="https://www.youtube.com/embed/{{ featured_product.featured_image.id }}"', source)


if __name__ == "__main__":
    unittest.main()
