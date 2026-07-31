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
        self.assertIn(
            "grid--{{ section.settings.products_per_row }}-col-desktop",
            featured_collection,
        )
        self.assertNotIn(
            'class="sales-collection spaced-section', featured_collection
        )
        self.assertIn("collection.product_count | default: 0", featured_collection)
        self.assertIn("collection_id != blank", featured_collection)
        self.assertNotIn("section.settings.products_to_display", featured_collection)
        self.assertNotIn("section.settings.collection == ''", featured_collection)

        homepage = self.settings["presets"]["editor"]
        self.assertEqual(
            homepage["content_for_index"],
            ["1667498127486", "1684403242688"],
        )
        self.assertNotIn("1684412368816", self.sections)
        self.assertNotIn("Marvel Super Heroes", self.settings_text)

        stylesheet = (THEME_ROOT / "assets" / "conversion-theme.css").read_text(
            encoding="utf-8"
        )
        self.assertIn(".template-index .spaced-section", stylesheet)
        self.assertIn("padding-top: clamp(1.8rem, 2.5vw, 3.2rem);", stylesheet)
        self.assertIn("min-height: 9rem;", stylesheet)
        self.assertIn("min-height: 8rem;", stylesheet)

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
        social_settings = footer["blocks"]["footer-2"]["settings"]
        self.assertEqual(
            social_settings["whatsapp"],
            "https://chat.whatsapp.com/L4f286YJNlxI7jPxfuzEV0",
        )
        self.assertEqual(
            social_settings["facebook"],
            "https://www.facebook.com/cardboardsg",
        )
        self.assertEqual(
            social_settings["carousell"],
            "https://www.carousell.sg/u/cardboard_collective/",
        )

        footer_liquid = (THEME_ROOT / "sections" / "footer.liquid").read_text(
            encoding="utf-8"
        )
        self.assertIn("icon-carousell", footer_liquid)
        self.assertIn(
            '"default": "https://www.facebook.com/cardboardsg"',
            footer_liquid,
        )
        self.assertIn(
            '"default": "https://chat.whatsapp.com/L4f286YJNlxI7jPxfuzEV0"',
            footer_liquid,
        )
        self.assertIn(
            '"default": "https://www.carousell.sg/u/cardboard_collective/"',
            footer_liquid,
        )
        self.assertIn('href="mailto:', footer_liquid)
        self.assertIn(
            "'https://cardboard.sg/pages/terms-of-service'", footer_liquid
        )
        self.assertNotIn("{% when 'quick_link' %}", footer_liquid)
        self.assertNotIn("{% when 'payment_accept' %}", footer_liquid)
        self.assertNotIn('"type": "quick_link"', footer_liquid)
        self.assertNotIn('"type": "payment_accept"', footer_liquid)

        svg_definitions = (
            THEME_ROOT / "snippets" / "svg-definitions.liquid"
        ).read_text(encoding="utf-8")
        carousell_icon = svg_definitions.split(
            "{% when 'icon-carousell' %}", maxsplit=1
        )[1].split("{% when 'icon-tiktok' %}", maxsplit=1)[0]
        self.assertIn('fill="currentColor"', carousell_icon)
        self.assertIn('viewBox="0 0 74 80"', carousell_icon)
        self.assertIn('fill-rule="evenodd"', carousell_icon)
        self.assertIn("M66.6 6.9V4", carousell_icon)
        self.assertNotIn("#ff2636", carousell_icon)
        self.assertNotIn('fill="#fff"', carousell_icon)

    def test_header_always_renders_categories_with_hierarchy_fallbacks(self) -> None:
        header = (THEME_ROOT / "sections" / "header.liquid").read_text(
            encoding="utf-8"
        )
        categories_snippet = (
            THEME_ROOT / "snippets" / "navigation-categories.liquid"
        )
        self.assertFalse(categories_snippet.exists())
        self.assertNotIn("navigation-categories", header)
        self.assertNotIn("if link.handle == categories_handle", header)
        self.assertEqual(
            header.count("for navigation_link in contents.main-menu.links"), 2
        )
        self.assertIn(
            "navigation_children = contents[navigation_link.handle].links",
            header,
        )
        self.assertIn("category_links = navigation_children", header)
        self.assertIn("category_links = contents.catalog.links", header)
        self.assertIn("category_links = contents.main-menu.links", header)
        self.assertEqual(header.count("for parentlink in category_links"), 2)
        self.assertEqual(
            header.count("if contents[child_handle].links != ''"), 2
        )
        self.assertEqual(header.count("for childlink in child"), 2)
        self.assertEqual(
            header.count("if contents[grand_handle].links != ''"), 2
        )
        self.assertEqual(header.count("for grandlink in grand"), 2)
        self.assertGreaterEqual(
            header.count("navigation_url contains 'wishlist'"), 10
        )
        self.assertGreaterEqual(
            header.count("navigation_title contains 'wishlist'"), 10
        )
        self.assertNotIn("{% continue %}", header)
        self.assertEqual(header.count('href="/collections/the-hobbit"'), 2)
        self.assertEqual(
            header.count('href="/collections/marvel-super-heroes"'), 2
        )
        self.assertEqual(header.count('href="/pages/about-us"'), 2)
        self.assertEqual(header.count('class="header__nav-item--categories"'), 1)
        self.assertEqual(
            header.count('class="menu-drawer__nav-item--categories"'), 1
        )
        desktop_categories_position = header.index(
            'class="header__nav-item--categories"'
        )
        self.assertLess(
            desktop_categories_position,
            header.index(
                'href="/collections/the-hobbit"', desktop_categories_position
            ),
        )
        self.assertEqual(header.count("<span>Categories</span>"), 2)
        self.assertIn('class="header__nav-item--about"', header)
        self.assertEqual(self.sections["header"]["settings"]["logo_max_width"], 90)

        stylesheet = (THEME_ROOT / "assets" / "conversion-theme.css").read_text(
            encoding="utf-8"
        )
        editor_stylesheet = (
            THEME_ROOT / "editor_assets" / "conversion-theme.css"
        ).read_text(encoding="utf-8")
        self.assertEqual(stylesheet, editor_stylesheet)
        self.assertIn("grid-template-areas: 'heading navigation icons';", stylesheet)
        self.assertIn(
            "grid-template-columns: auto minmax(0, 1fr) auto;", stylesheet
        )
        self.assertIn("flex-wrap: nowrap;", stylesheet)
        self.assertIn("width: 100%;", stylesheet)
        self.assertIn(".header--middle-left .header__nav-item--about", stylesheet)
        self.assertIn("margin-left: auto;", stylesheet)
        self.assertIn("padding-top: 0;", stylesheet)
        self.assertIn("padding-bottom: 0;", stylesheet)


if __name__ == "__main__":
    unittest.main()
