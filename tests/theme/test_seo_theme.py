from __future__ import annotations

import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
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
        # No fallback names: listing the domain handed Google "cardboard.sg"
        # as the site name, and repeating the name gave it nothing new.
        self.assertNotIn("alternateName", website)
        self.assertIn('"@id": "https://cardboard.sg/#organization"', website)

        self.assertIn('"@type": "OnlineStore"', organization)
        self.assertIn('"name": {{ shop.name | json }}', organization)
        self.assertIn('"legalName": "Cardboard Collective Pte. Ltd."', organization)
        self.assertIn("Singapore-based online retailer", organization)
        self.assertNotIn('"@type": "PostalAddress"', organization)
        self.assertNotIn('"streetAddress"', organization)
        self.assertIn('"hasMerchantReturnPolicy"', organization)
        self.assertIn(
            '"merchantReturnLink": "https://cardboard.sg/pages/refund-policy"',
            organization,
        )

    def test_favicon_is_linked_in_a_format_google_accepts(self) -> None:
        # The image CDN serves a bare URL as WebP, which Google Search does not
        # accept for favicons; any query string returns the uploaded PNG.
        layout = (THEME_ROOT / "layout" / "theme.liquid").read_text(encoding="utf-8")

        self.assertIn(
            "{% assign favicon_url = favicon_url | append: '?format=png' %}", layout
        )
        self.assertIn('<link rel="icon" href="{{ favicon_url }}" />', layout)
        self.assertNotIn('href="{{ settings.favicon_img }}"', layout)

        for config in ("config", "editor_config"):
            with self.subTest(config=config):
                settings = (THEME_ROOT / config / "settings_data.json").read_text(
                    encoding="utf-8"
                )
                self.assertIn(
                    '"favicon_img": "https://cdn.store-assets.com/s/1441746/f/18181591.png"',
                    settings,
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

    def test_product_schema_describes_preorders_brand_shipping_and_returns(self) -> None:
        section = (THEME_ROOT / "sections" / "main-product.liquid").read_text(
            encoding="utf-8"
        )
        schema = (THEME_ROOT / "snippets" / "product-schema.liquid").read_text(
            encoding="utf-8"
        )

        # EasyStore's built-in filter marked pre-orders InStock and branded
        # every bundle with the store name.
        self.assertNotIn("structured_data", section)
        self.assertIn("{% include 'product-schema' %}", section)

        self.assertIn('"@type": "Product"', schema)
        self.assertIn("{% if product_schema_price_value > 0 %}", schema)
        self.assertIn("{% if product.tags contains 'Pre-order' %}", schema)
        self.assertIn("https://schema.org/PreOrder", schema)
        self.assertIn("{% if product.tags contains 'MTG' %}", schema)
        self.assertIn("'Magic: The Gathering'", schema)
        self.assertIn('"gtin"', schema)
        self.assertIn('"shippingDetails"', schema)
        self.assertIn("{% if product_schema_price_value >= 500 %}", schema)
        self.assertIn('"addressCountry": "SG"', schema)
        self.assertIn("https://schema.org/MerchantReturnNotPermitted", schema)
        self.assertIn('"@id": "https://cardboard.sg/#organization"', schema)

    def test_store_plumbing_pages_are_kept_out_of_the_index(self) -> None:
        layout = (THEME_ROOT / "layout" / "theme.liquid").read_text(encoding="utf-8")
        robots = (THEME_ROOT / "snippets" / "robots-meta.liquid").read_text(
            encoding="utf-8"
        )

        self.assertIn("{% include 'robots-meta' %}", layout)
        for handle in ("feature-on-homepage", "product-types", "exclusive-add-ons"):
            with self.subTest(handle=handle):
                self.assertIn(f"collection.handle == '{handle}'", robots)
        self.assertIn("product.handle contains 'exclusive-add-on-'", robots)
        self.assertIn('<meta name="robots" content="noindex, follow">', robots)

    def test_paginated_collections_point_their_canonical_at_themselves(self) -> None:
        layout = (THEME_ROOT / "layout" / "theme.liquid").read_text(encoding="utf-8")

        self.assertIn('<link rel="canonical" href="{{ page_canonical_url }}">', layout)
        self.assertNotIn('<link rel="canonical" href="{{ canonical_url }}">', layout)
        self.assertIn("append: '?page=' | append: current_page", layout)

    def test_twitter_descriptions_use_the_written_meta_description(self) -> None:
        social = (THEME_ROOT / "snippets" / "social-meta-tags.liquid").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("pages[settings.home_page_content].content", social)
        self.assertIn(
            "page_description | default: product.description | strip_html", social
        )
        self.assertIn(
            "page_description | default: shop.description | strip_html", social
        )

    def test_product_images_do_not_use_upload_file_names_as_alt_text(self) -> None:
        alt = (THEME_ROOT / "snippets" / "product-image-alt.liquid").read_text(
            encoding="utf-8"
        )
        for marker in ("Screenshot", "WhatsApp Image", "image_", "IMG_"):
            with self.subTest(marker=marker):
                self.assertIn(f"contains '{marker}'", alt)
        self.assertIn("product_image_alt_words.size < 2", alt)

        for path in (
            "sections/main-product.liquid",
            "snippets/product-card.liquid",
            "snippets/product-quickview.liquid",
        ):
            source = (THEME_ROOT / path).read_text(encoding="utf-8")
            with self.subTest(path=path):
                self.assertIn("{% include 'product-image-alt'", source)
                self.assertNotIn(".alt | _default: product.title", source)

    def test_homepage_links_shared_collection_styles_once(self) -> None:
        section = (THEME_ROOT / "sections" / "featured-collection.liquid").read_text(
            encoding="utf-8"
        )

        self.assertTrue(section.startswith("{% comment %}"))
        self.assertIn("{% unless featured_collection_assets_loaded %}", section)
        self.assertIn("{% assign featured_collection_assets_loaded = true %}", section)
        self.assertLess(
            section.index("{% unless featured_collection_assets_loaded %}"),
            section.index("component-card.css"),
        )

if __name__ == "__main__":
    unittest.main()
