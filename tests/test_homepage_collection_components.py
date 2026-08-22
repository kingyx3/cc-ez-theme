from __future__ import annotations

import json
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
THEME_ROOT = REPOSITORY_ROOT / "theme"


class HomepageCollectionComponentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        settings = json.loads(
            (THEME_ROOT / "config" / "settings_data.json").read_text(
                encoding="utf-8"
            )
        )
        cls.homepage = settings["presets"]["editor"]
        cls.sections = cls.homepage["sections"]

    def test_homepage_collection_sections_share_one_component_format(self) -> None:
        section_ids = self.homepage["content_for_index"]
        self.assertGreaterEqual(len(section_ids), 2)

        best_sellers = self.sections[section_ids[0]]
        self.assertEqual(best_sellers["settings"]["title"], "Best Sellers")

        shared_settings = (
            "products_per_row",
            "show_view_all",
            "image_ratio",
            "show_secondary_image",
            "swipe_on_mobile",
            "center_title",
            "show_product_info",
        )
        for section_id in section_ids:
            section = self.sections[section_id]
            with self.subTest(section=section["settings"]["title"]):
                self.assertEqual(section["type"], "featured-collection")
                for setting_name in shared_settings:
                    self.assertEqual(
                        section["settings"][setting_name],
                        best_sellers["settings"][setting_name],
                    )

    def test_homepage_collections_keep_themed_accent_colors(self) -> None:
        expected_accents = {
            "Best Sellers": "#C44120",
            "[Pre-order] Reality Fracture": "#00897B",
            "The Hobbit Collection": "#3559D9",
            "Marvel Collection": "#C62828",
            "Secrets of Strixhaven": "#7B2CBF",
        }
        actual_accents = {
            self.sections[section_id]["settings"]["title"]: self.sections[section_id][
                "settings"
            ]["accent_color"]
            for section_id in self.homepage["content_for_index"]
        }
        self.assertEqual(actual_accents, expected_accents)

    def test_featured_collection_section_composes_reusable_snippets(self) -> None:
        section = (
            THEME_ROOT / "sections" / "featured-collection.liquid"
        ).read_text(encoding="utf-8")
        header = (
            THEME_ROOT / "snippets" / "featured-collection-header.liquid"
        ).read_text(encoding="utf-8")
        products = (
            THEME_ROOT / "snippets" / "featured-collection-products.liquid"
        ).read_text(encoding="utf-8")

        self.assertIn("{% include 'featured-collection-header'", section)
        self.assertIn("{% include 'featured-collection-products'", section)
        self.assertNotIn('class="sales-collection__header', section)
        self.assertNotIn("{% include 'product-card'", section)

        self.assertIn('class="sales-collection__header', header)
        self.assertIn("section.settings.eyebrow", header)
        self.assertIn("section.settings.subtitle", header)
        self.assertIn("section.settings.show_view_all", header)

        self.assertIn('class="sales-collection__grid', products)
        self.assertIn("{% include 'product-card'", products)
        self.assertIn("show_add_to_cart_button: false", products)
        self.assertIn("section.settings.products_per_row", products)
        self.assertIn("section.settings.swipe_on_mobile", products)


if __name__ == "__main__":
    unittest.main()
