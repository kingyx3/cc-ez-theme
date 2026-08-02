from __future__ import annotations

import json
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
THEME_ROOT = REPOSITORY_ROOT / "theme"


class ProductListingCartControlTests(unittest.TestCase):
    def test_global_toggle_is_available_in_storefront_and_editor(self) -> None:
        schemas = []
        for directory in ("config", "editor_config"):
            schema = json.loads(
                (THEME_ROOT / directory / "settings_schema.json").read_text(
                    encoding="utf-8"
                )
            )
            schemas.append(schema)

            collection_options = next(
                group["options"]
                for group in schema["options"]
                if group["label"]["en_US"] == "Collection"
            )
            toggle = next(
                option
                for option in collection_options
                if option.get("id") == "show_add_to_cart_button"
            )
            self.assertEqual(toggle["type"], "checkbox")
            self.assertTrue(toggle["default"])

        self.assertEqual(schemas[0], schemas[1])

    def test_product_cards_use_the_global_toggle_on_every_listing(self) -> None:
        product_card = (
            THEME_ROOT / "snippets" / "product-card.liquid"
        ).read_text(encoding="utf-8")

        self.assertIn("settings.show_add_to_cart_button", product_card)
        self.assertIn("{% if show_listing_add_to_cart %}", product_card)
        self.assertNotIn("{% if show_add_to_cart_button %}", product_card)
        self.assertIn("<add-to-cart-button>", product_card)

    def test_listing_cart_buttons_are_not_clipped_by_card_borders(self) -> None:
        stylesheets = []
        for directory in ("assets", "editor_assets"):
            stylesheet = (
                THEME_ROOT / directory / "component-card.css"
            ).read_text(encoding="utf-8")
            stylesheets.append(stylesheet)

            self.assertIn("overflow: visible !important;", stylesheet)
            self.assertIn("isolation: isolate;", stylesheet)
            self.assertIn(
                ".product-card-wrapper > add-to-cart-button .card__badge",
                stylesheet,
            )
            self.assertIn("z-index: 5;", stylesheet)

        self.assertEqual(stylesheets[0], stylesheets[1])


if __name__ == "__main__":
    unittest.main()
