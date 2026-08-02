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

    def test_product_images_inherit_and_clip_to_the_card_radius(self) -> None:
        stylesheet = (
            THEME_ROOT / "assets" / "card-navigation-polish.css"
        ).read_text(encoding="utf-8")

        self.assertIn(".product-card-wrapper > a", stylesheet)
        self.assertIn("border-radius: inherit", stylesheet)
        self.assertIn(".product-card-wrapper > a > .card--product .media", stylesheet)
        self.assertIn(".card--product .media > img", stylesheet)
        self.assertIn("overflow: hidden", stylesheet)
        self.assertIn("border-bottom-left-radius: 0", stylesheet)
        self.assertIn("border-bottom-right-radius: 0", stylesheet)
        self.assertIn(".card--product:only-child", stylesheet)
        self.assertNotIn("--product-card-visual-radius", stylesheet)

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
