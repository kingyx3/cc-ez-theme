from __future__ import annotations

import json
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
THEME_ROOT = REPOSITORY_ROOT / "theme"


class StorefrontConfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings_path = THEME_ROOT / "config" / "settings_data.json"
        cls.editor_settings_path = (
            THEME_ROOT / "editor_config" / "settings_data.json"
        )
        cls.settings_text = cls.settings_path.read_text(encoding="utf-8")
        cls.settings = json.loads(cls.settings_text)
        cls.sections = cls.settings["presets"]["editor"]["sections"]

    def test_storefront_and_editor_settings_match(self) -> None:
        self.assertEqual(
            self.settings_text,
            self.editor_settings_path.read_text(encoding="utf-8"),
        )

    def test_product_page_does_not_advertise_worldwide_shipping(self) -> None:
        product_section = self.sections["main-product"]
        rendered_text = [
            block["settings"].get("text")
            for block in product_section["blocks"].values()
        ]
        self.assertNotIn("Worldwide shipping", rendered_text)

    def test_homepage_collections_are_six_products_in_three_columns(self) -> None:
        expected = {
            "1667498127486": ("Best Sellers", "feature-on-homepage"),
            "1684403242688": ("The Hobbit Collection", "the-hobbit"),
        }
        for section_id, (title, collection_id) in expected.items():
            section = self.sections[section_id]
            with self.subTest(section=title):
                self.assertEqual(section["type"], "featured-collection")
                self.assertEqual(section["settings"]["title"], title)
                self.assertEqual(
                    section["settings"]["collection__id"], collection_id
                )
                self.assertEqual(section["settings"]["products_per_row"], 3)
                self.assertEqual(section["settings"]["products_to_show"], 6)

        featured_collection = (
            THEME_ROOT / "sections" / "featured-collection.liquid"
        ).read_text(encoding="utf-8")
        self.assertIn("show_add_to_cart_button: false", featured_collection)

    def test_footer_contains_only_social_and_contact_default_blocks(self) -> None:
        footer = self.sections["footer"]
        self.assertEqual(footer["blocks_order"], ["footer-2", "footer-1"])
        self.assertEqual(
            {block["type"] for block in footer["blocks"].values()},
            {"follow_us", "about_us"},
        )
        self.assertEqual(
            footer["blocks"]["footer-1"]["settings"],
            {"title": "Contact Us", "email": "contact@cardboard.sg"},
        )
        self.assertEqual(
            footer["blocks"]["footer-2"]["settings"]["carousell"],
            "https://www.carousell.sg/u/cardboard_collective/",
        )

        footer_liquid = (THEME_ROOT / "sections" / "footer.liquid").read_text(
            encoding="utf-8"
        )
        self.assertIn("icon-carousell", footer_liquid)
        self.assertIn('href="mailto:', footer_liquid)
        self.assertIn("'/pages/terms-of-service'", footer_liquid)
        self.assertNotIn("{% when 'quick_link' %}", footer_liquid)
        self.assertNotIn("{% when 'payment_accept' %}", footer_liquid)
        self.assertNotIn('"type": "quick_link"', footer_liquid)
        self.assertNotIn('"type": "payment_accept"', footer_liquid)

    def test_header_is_compact_and_filters_wishlist_links(self) -> None:
        header = (THEME_ROOT / "sections" / "header.liquid").read_text(
            encoding="utf-8"
        )
        self.assertIn("link.url contains 'wishlist'", header)
        self.assertEqual(self.sections["header"]["settings"]["logo_max_width"], 90)

        stylesheet = (THEME_ROOT / "assets" / "conversion-theme.css").read_text(
            encoding="utf-8"
        )
        editor_stylesheet = (
            THEME_ROOT / "editor_assets" / "conversion-theme.css"
        ).read_text(encoding="utf-8")
        self.assertEqual(stylesheet, editor_stylesheet)
        self.assertIn("grid-template-areas: 'heading navigation icons';", stylesheet)
        self.assertIn("grid-template-columns: auto minmax(0, 1fr) auto;", stylesheet)
        self.assertIn("flex-wrap: nowrap;", stylesheet)
        self.assertIn("padding-top: 0;", stylesheet)
        self.assertIn("padding-bottom: 0;", stylesheet)


if __name__ == "__main__":
    unittest.main()
