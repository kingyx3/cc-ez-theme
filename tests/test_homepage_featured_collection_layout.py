from __future__ import annotations

import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FEATURED_COLLECTION = (
    REPOSITORY_ROOT / "theme" / "sections" / "featured-collection.liquid"
)


class HomepageFeaturedCollectionLayoutTests(unittest.TestCase):
    def test_non_best_seller_home_sections_render_three_products(self) -> None:
        template = FEATURED_COLLECTION.read_text(encoding="utf-8")

        self.assertIn(
            "{% assign products_to_show = section.settings.products_to_show %}",
            template,
        )
        for section_id in (
            "1787270400000",
            "1684403242688",
            "1684412368816",
            "1684412368817",
        ):
            with self.subTest(section_id=section_id):
                self.assertIn(section_id, template)

        self.assertNotIn("1667498127486", template)
        self.assertIn("{% assign products_to_show = 3 %}", template)
        self.assertIn(
            "{% for product in collection.products limit: products_to_show %}",
            template,
        )
        self.assertNotIn(
            "{% for product in collection.products limit: section.settings.products_to_show %}",
            template,
        )


if __name__ == "__main__":
    unittest.main()
