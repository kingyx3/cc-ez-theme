from __future__ import annotations

import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
THEME_ROOT = REPOSITORY_ROOT / "theme"


class SeoThemeTests(unittest.TestCase):
    def test_homepage_keeps_ui_neutral_and_renders_organization_schema(self) -> None:
        home = (THEME_ROOT / "templates" / "home.liquid").read_text(encoding="utf-8")
        organization = (
            THEME_ROOT / "snippets" / "organization-schema.liquid"
        ).read_text(encoding="utf-8")

        self.assertIn("{% include 'organization-schema' %}", home)
        self.assertIn('<h1 class="visually-hidden">{{ shop.name | escape }}</h1>', home)
        self.assertNotIn("{% section 'seo-intro' %}", home)
        self.assertFalse((THEME_ROOT / "sections" / "seo-intro.liquid").exists())
        self.assertIn('"@type": "OnlineStore"', organization)
        self.assertIn('"hasMerchantReturnPolicy"', organization)
        self.assertIn(
            '"merchantReturnLink": "https://cardboard.sg/legal/refund-policy"',
            organization,
        )

    def test_product_and_collection_templates_render_breadcrumbs(self) -> None:
        for template_name in ("product.liquid", "collection.liquid"):
            template = (THEME_ROOT / "templates" / template_name).read_text(
                encoding="utf-8"
            )
            with self.subTest(template=template_name):
                self.assertIn("{% include 'breadcrumbs' %}", template)
                self.assertIn("{% include 'breadcrumb-schema' %}", template)

        breadcrumbs = (THEME_ROOT / "snippets" / "breadcrumbs.liquid").read_text(
            encoding="utf-8"
        )
        breadcrumb_schema = (
            THEME_ROOT / "snippets" / "breadcrumb-schema.liquid"
        ).read_text(encoding="utf-8")

        self.assertIn('aria-label="Breadcrumb"', breadcrumbs)
        self.assertIn('aria-current="page"', breadcrumbs)
        self.assertIn('"@type": "BreadcrumbList"', breadcrumb_schema)
        self.assertIn('"position": 3', breadcrumb_schema)
        self.assertIn("canonical_url | json", breadcrumb_schema)


if __name__ == "__main__":
    unittest.main()
