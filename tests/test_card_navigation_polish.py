from __future__ import annotations

import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
THEME_ROOT = REPOSITORY_ROOT / "theme"


class CardNavigationPolishTests(unittest.TestCase):
    def test_polish_stylesheet_is_loaded_globally(self) -> None:
        currencies = (THEME_ROOT / "snippets" / "currencies.liquid").read_text(
            encoding="utf-8"
        )

        self.assertIn("card-navigation-polish.css", currencies)

    def test_storefront_and_editor_styles_match(self) -> None:
        storefront = (
            THEME_ROOT / "assets" / "card-navigation-polish.css"
        ).read_text(encoding="utf-8")
        editor = (
            THEME_ROOT / "editor_assets" / "card-navigation-polish.css"
        ).read_text(encoding="utf-8")

        self.assertEqual(storefront, editor)

    def test_product_images_are_clipped_to_the_card_radius(self) -> None:
        stylesheet = (
            THEME_ROOT / "assets" / "card-navigation-polish.css"
        ).read_text(encoding="utf-8")

        self.assertIn("--product-card-visual-radius: 1.2rem", stylesheet)
        self.assertIn("--product-card-visual-radius: 1.6rem", stylesheet)
        self.assertIn(".product-card-wrapper > a > .card--product .media", stylesheet)
        self.assertIn("overflow: hidden", stylesheet)
        self.assertIn("border-radius: var(--product-card-visual-radius)", stylesheet)
        self.assertIn(".card--product:only-child", stylesheet)

    def test_browse_arrows_are_reduced_on_desktop_only(self) -> None:
        stylesheet = (
            THEME_ROOT / "assets" / "card-navigation-polish.css"
        ).read_text(encoding="utf-8")

        desktop_media = "@media screen and (min-width: 990px)"
        arrow_selector = (
            ".header__nav-item--browse .header__menu-item > .icon-caret"
        )
        self.assertIn(desktop_media, stylesheet)
        self.assertIn(arrow_selector, stylesheet)
        self.assertIn("width: 0.8rem", stylesheet)
        self.assertIn("height: 0.8rem", stylesheet)
        self.assertNotIn(".menu-drawer__menu-item > .icon-caret", stylesheet)


if __name__ == "__main__":
    unittest.main()
