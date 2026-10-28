"""Guard lazy loading for offscreen YouTube videos in product media carousels."""
from __future__ import annotations

import unittest
from pathlib import Path

from liquid import Template


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
            '{% if has_selected_featured_media or forloop.index > 1 %}loading="lazy"{% else %}loading="eager"{% endif %} allowfullscreen',
            source,
        )
        self.assertIn('src="https://www.youtube.com/embed/{{ featured_product.selected_or_first_available_variant.featured_image.id }}"', source)
        self.assertIn(
            '{% if has_selected_featured_media or forloop.index > 1 %}loading="lazy"{% else %}loading="eager"{% endif %}>',
            source,
        )
        self.assertNotIn('embed/{{ featured_product.featured_image.id }}', source)


    def test_featured_video_priority_behaves_for_both_gallery_modes(self) -> None:
        """Test the actual Liquid branch, including the selected-variant case."""
        source = (THEME / "sections" / "featured-product.liquid").read_text(
            encoding="utf-8"
        )
        guard = (
            '{% if has_selected_featured_media or forloop.index > 1 %}'
            'loading="lazy"{% else %}loading="eager"{% endif %}'
        )
        self.assertIn(guard, source)
        for has_selected, index, expected in (
            (True, 1, 'loading="lazy"'),
            (True, 2, 'loading="lazy"'),
            (False, 1, 'loading="eager"'),
            (False, 2, 'loading="lazy"'),
        ):
            with self.subTest(has_selected=has_selected, slide=index):
                rendered = Template(guard).render(
                    has_selected_featured_media=has_selected,
                    forloop={"index": index},
                )
                self.assertEqual(rendered, expected)

    def test_selected_variant_video_uses_selected_media_not_main_image(self) -> None:
        source = (THEME / "sections" / "featured-product.liquid").read_text(
            encoding="utf-8"
        )
        selected_id = (
            "featured_product.selected_or_first_available_variant.featured_image.id"
        )
        self.assertIn('embed/{{ ' + selected_id + ' }}', source)
        rendered = Template('embed/{{ ' + selected_id + ' }}').render(
            featured_product={
                "featured_image": {"id": "wrong-main-image"},
                "selected_or_first_available_variant": {
                    "featured_image": {"id": "selected-variant-video"}
                },
            }
        )
        self.assertEqual(rendered, "embed/selected-variant-video")


if __name__ == "__main__":
    unittest.main()
