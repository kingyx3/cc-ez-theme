from __future__ import annotations

import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
THEME_ROOT = REPOSITORY_ROOT / "theme"


class SeoThemeTests(unittest.TestCase):
    def test_homepage_pins_brand_identity_without_adding_visible_seo_copy(self) -> None:
        home = (THEME_ROOT / "templates" / "home.liquid").read_text(encoding="utf-8")
        website = (THEME_ROOT / "snippets" / "website-schema.liquid").read_text(
            encoding="utf-8"
        )
        organization = (
            THEME_ROOT / "snippets" / "organization-schema.liquid"
        ).read_text(encoding="utf-8")

        self.assertIn("{% include 'website-schema' %}", home)
        self.assertIn("{% include 'organization-schema' %}", home)
        self.assertIn('<h1 class="visually-hidden">{{ shop.name | escape }}</h1>', home)
        self.assertNotIn("{% section 'seo-intro' %}", home)
        self.assertFalse((THEME_ROOT / "sections" / "seo-intro.liquid").exists())

        self.assertIn('"@type": "WebSite"', website)
        self.assertIn('"@id": "https://cardboard.sg/#website"', website)
        self.assertIn('"name": {{ shop.name | json }}', website)
        self.assertIn('"alternateName": ["cardboard.sg"]', website)
        self.assertIn('"@id": "https://cardboard.sg/#organization"', website)

        self.assertIn('"@type": "OnlineStore"', organization)
        self.assertIn('"name": {{ shop.name | json }}', organization)
        self.assertIn('"legalName": "Cardboard Collective Pte. Ltd."', organization)
        self.assertIn("Singapore-based online retailer", organization)
        self.assertNotIn('"@type": "PostalAddress"', organization)
        self.assertNotIn('"streetAddress"', organization)
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

    def test_current_breadcrumb_ellipsis_is_not_applied_to_a_flex_item(self) -> None:
        # `text-overflow: ellipsis` never renders on an element that is itself
        # `display: flex` (the flex algorithm blockifies its children instead of
        # laying out the element's own text run) - confirmed on a live mobile
        # screenshot of the product page, where the long final crumb (the
        # product title) ran off the right edge of the screen with no "..." and
        # no wrap, while the earlier `<a>` crumbs truncated correctly because
        # the ellipsis styles sat on a plain child element, not the flex `<li>`
        # itself. The current crumb needs the same shape: the ellipsis rule
        # belongs to an inner span, not to `.breadcrumbs__current` on the `<li>`.
        breadcrumbs = (THEME_ROOT / "snippets" / "breadcrumbs.liquid").read_text(
            encoding="utf-8"
        )

        self.assertIn(".breadcrumbs__current-text {", breadcrumbs)
        self.assertIn("text-overflow: ellipsis", breadcrumbs)
        self.assertNotRegex(
            breadcrumbs,
            r"\.breadcrumbs__current\s*\{[^}]*text-overflow",
            msg="the ellipsis rule must target the inner span, not the flex <li>",
        )
        self.assertEqual(
            breadcrumbs.count('<span class="breadcrumbs__current-text">'),
            2,
            "both the collection and product current-crumb branches must wrap "
            "their text in the ellipsis span",
        )


if __name__ == "__main__":
    unittest.main()
