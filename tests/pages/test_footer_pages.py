import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "pages"))
from deploy_footer_pages import (
    HANDLES, detail_page, digest, is_published, page_list, render_sources, visible_text
)


class FooterPagesTest(unittest.TestCase):
    def test_exact_six_sources_and_html_markup(self):
        pages = render_sources()
        self.assertEqual(set(HANDLES), set(pages))
        for name, html in pages.items():
            with self.subTest(name=name):
                self.assertTrue(html.startswith("<h2>"))
                self.assertEqual(html.count("<h2>"), 1)
                self.assertNotIn("<script", html)
                self.assertGreater(len(visible_text(html)), 80)

    def test_thresholds_and_checkout_match_across_pages(self):
        pages = render_sources()
        terms = visible_text(pages["terms-of-service"])
        payment = visible_text(pages["payment"])
        shipping = visible_text(pages["shipping-policy"])
        contact = visible_text(pages["contact-us"])
        self.assertIn("15 minutes", terms)
        self.assertIn("15 minutes", payment)
        self.assertIn("S$500 or more", terms)
        self.assertIn("S$500 or more", shipping)
        self.assertIn("S$1,000 or more", terms)
        self.assertIn("S$1,000 or more", contact)
        self.assertNotIn("24 hours", terms)
        self.assertNotIn("quote the order reference", terms)

    def test_only_valid_list_handles_are_selected(self):
        payload = {"data": {"pages": {"data": [
            {"id": 12, "handle": "contact-us"},
            {"id": 15, "handle": "some-other-page"},
            {"id": 16, "name": "Page without handle"},
        ]}}}
        self.assertEqual(page_list(payload), [{"id": 12, "handle": "contact-us"}])

    def test_details_and_publication_guard(self):
        data = {"data": {"page": {"id": 4, "handle": "payment", "body_html": "<p>Payment</p>", "is_published": 1}}}
        page = detail_page(data, 4)
        self.assertTrue(is_published(page))
        self.assertFalse(is_published({"is_published": 0}))
        self.assertFalse(is_published({"is_published": 2}))
        self.assertFalse(is_published({"is_published": False}))

    def test_visible_text_and_digest(self):
        self.assertEqual(visible_text("<h2>A&amp;B</h2><p>C  D</p>"), "A&B C D")
        self.assertEqual(digest("abc"), digest("abc"))
        self.assertNotEqual(digest("abc"), digest("abd"))


if __name__ == "__main__":
    unittest.main()
