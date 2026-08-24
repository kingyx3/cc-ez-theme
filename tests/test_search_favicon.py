from pathlib import Path
import hashlib
import struct
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SEARCH_FAVICON = REPOSITORY_ROOT / "search-assets" / "cc-favicon-96.png"
THEME_ROOT = REPOSITORY_ROOT / "theme"
STABLE_SEARCH_FAVICON_URL = (
    "https://raw.githubusercontent.com/kingyx3/cc-ez-theme/"
    "main/search-assets/cc-favicon-96.png"
)
EXPECTED_FAVICON_SHA256 = (
    "0ad2480e466cfc7c5f65a671af6bf0e97b3b5d8a4be1d0bf3a511cecc2a435cc"
)


class SearchFaviconTests(unittest.TestCase):
    def test_bry_search_favicon_is_stable_and_explicit(self) -> None:
        favicon = SEARCH_FAVICON.read_bytes()
        self.assertEqual(favicon[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(struct.unpack(">II", favicon[16:24]), (96, 96))
        self.assertEqual(hashlib.sha256(favicon).hexdigest(), EXPECTED_FAVICON_SHA256)

        social_meta = (
            THEME_ROOT / "snippets" / "social-meta-tags.liquid"
        ).read_text(encoding="utf-8")
        self.assertIn(
            f'rel="icon" type="image/png" sizes="96x96" href="{STABLE_SEARCH_FAVICON_URL}"',
            social_meta,
        )
        self.assertIn(
            f'rel="shortcut icon" type="image/png" href="{STABLE_SEARCH_FAVICON_URL}"',
            social_meta,
        )

        layout = (THEME_ROOT / "layout" / "theme.liquid").read_text(
            encoding="utf-8"
        )
        self.assertIn("{% include 'social-meta-tags' %}", layout)
        self.assertLess(
            layout.index('href="{{ settings.favicon_img }}"'),
            layout.index("{% include 'social-meta-tags' %}"),
        )


if __name__ == "__main__":
    unittest.main()
