from pathlib import Path
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
THEME_ROOT = REPOSITORY_ROOT / "theme"


class FaviconTests(unittest.TestCase):
    def test_codebase_favicon_is_used_and_mirrored(self) -> None:
        storefront_favicon = THEME_ROOT / "assets" / "cc-favicon.png"
        editor_favicon = THEME_ROOT / "editor_assets" / "cc-favicon.png"
        layout = (THEME_ROOT / "layout" / "theme.liquid").read_text(
            encoding="utf-8"
        )

        self.assertTrue(storefront_favicon.is_file())
        self.assertEqual(storefront_favicon.read_bytes(), editor_favicon.read_bytes())
        self.assertTrue(storefront_favicon.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertIn("{{ 'cc-favicon.png' | asset_url }}", layout)
        self.assertNotIn('href="{{ settings.favicon_img }}"', layout)


if __name__ == "__main__":
    unittest.main()
