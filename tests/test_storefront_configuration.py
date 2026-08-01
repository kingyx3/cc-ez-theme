from __future__ import annotations

import json
import re
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

    def test_product_page_has_buy_now_checkout_action(self) -> None:
        main_product = (
            THEME_ROOT / "sections" / "main-product.liquid"
        ).read_text(encoding="utf-8")
        self.assertRegex(
            main_product,
            r'name="add"[\s\S]+?class="[^"]*'
            r'product-form__submit--secondary[^"]*button--secondary',
        )
        self.assertRegex(
            main_product,
            r'name="buy_now"[\s\S]+?class="[^"]*'
            r'product-form__buy-now[^"]*button--primary',
        )
        self.assertIn("Buy now", main_product)

        product_form = (
            THEME_ROOT / "assets" / "product-form.js"
        ).read_text(encoding="utf-8")
        editor_product_form = (
            THEME_ROOT / "editor_assets" / "product-form.js"
        ).read_text(encoding="utf-8")
        self.assertEqual(product_form, editor_product_form)
        self.assertIn("evt.submitter", product_form)
        self.assertIn("serializeForm(this.form)", product_form)
        self.assertIn("EasyStore.Action.addToCart", product_form)
        self.assertIn("submitButton.name === 'buy_now'", product_form)
        self.assertIn("window.location.assign('/checkout')", product_form)
        self.assertLess(
            product_form.index("cart.description != undefined"),
            product_form.index("if(buyNow)"),
        )

        for asset_directory in ("assets", "editor_assets"):
            stylesheet = (
                THEME_ROOT / asset_directory / "section-main-product.css"
            ).read_text(encoding="utf-8")
            self.assertIn(".product-form__submit--secondary", stylesheet)
            self.assertIn(
                "--color-button: var(--color-base-accent-1);",
                stylesheet,
            )
            self.assertIn(
                "--color-button-text: var(--color-base-accent-1);",
                stylesheet,
            )

        global_script = (
            THEME_ROOT / "assets" / "global.js"
        ).read_text(encoding="utf-8")
        self.assertIn("'[name=\"buy_now\"]'", global_script)
        self.assertIn(
            "querySelectorAll('.product-form__submit')", global_script
        )

    def test_homepage_collections_are_six_products_in_three_columns(self) -> None:
        expected = {
            "1667498127486": ("Best Sellers", "feature-on-homepage"),
            "1684403242688": ("The Hobbit Collection", "the-hobbit"),
            "1684412368816": ("Marvel Collection", "marvel-super-heroes"),
            "1684412368817": (
                "Secrets of Strixhaven",
                "secrets-of-strixhaven",
            ),
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
            [
                "1667498127486",
                "1684403242688",
                "1684412368816",
                "1684412368817",
            ],
        )

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

    def test_header_uses_fixed_collection_shortcuts_without_category(self) -> None:
        header = (THEME_ROOT / "sections" / "header.liquid").read_text(
            encoding="utf-8"
        )
        categories_snippet = (
            THEME_ROOT / "snippets" / "navigation-categories.liquid"
        )
        self.assertFalse(categories_snippet.exists())
        self.assertNotIn("navigation-categories", header)
        self.assertNotIn("category_links", header)
        self.assertNotIn("contents.catalog.links", header)
        self.assertNotIn('class="header__nav-item--categories"', header)
        self.assertNotIn('class="menu-drawer__nav-item--categories"', header)
        self.assertNotIn("<span>Category</span>", header)
        self.assertNotIn("<span>Categories</span>", header)
        self.assertNotIn("{% continue %}", header)
        self.assertEqual(header.count('href="/collections/the-hobbit"'), 2)
        self.assertEqual(
            header.count('href="/collections/marvel-super-heroes"'), 2
        )
        self.assertEqual(
            header.count('href="/collections/secrets-of-strixhaven"'), 2
        )
        self.assertEqual(header.count('href="/pages/about-us"'), 2)

        first_hobbit = header.index('href="/collections/the-hobbit"')
        first_marvel = header.index(
            'href="/collections/marvel-super-heroes"', first_hobbit
        )
        first_strixhaven = header.index(
            'href="/collections/secrets-of-strixhaven"', first_marvel
        )
        first_about = header.index('href="/pages/about-us"', first_strixhaven)
        self.assertLess(first_hobbit, first_marvel)
        self.assertLess(first_marvel, first_strixhaven)
        self.assertLess(first_strixhaven, first_about)

        second_hobbit = header.index(
            'href="/collections/the-hobbit"', first_about
        )
        second_marvel = header.index(
            'href="/collections/marvel-super-heroes"', second_hobbit
        )
        second_strixhaven = header.index(
            'href="/collections/secrets-of-strixhaven"', second_marvel
        )
        second_about = header.index('href="/pages/about-us"', second_strixhaven)
        self.assertLess(second_hobbit, second_marvel)
        self.assertLess(second_marvel, second_strixhaven)
        self.assertLess(second_strixhaven, second_about)
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

    def test_wishlist_is_removed_from_all_theme_surfaces(self) -> None:
        header = (THEME_ROOT / "sections" / "header.liquid").read_text(
            encoding="utf-8"
        )
        account = (
            THEME_ROOT / "templates" / "customers" / "account.liquid"
        ).read_text(encoding="utf-8")
        global_script = (THEME_ROOT / "assets" / "global.js").read_text(
            encoding="utf-8"
        )
        editor_script = (
            THEME_ROOT / "editor_assets" / "global.js"
        ).read_text(encoding="utf-8")
        stylesheet = (
            THEME_ROOT / "assets" / "conversion-theme.css"
        ).read_text(encoding="utf-8")

        self.assertGreaterEqual(header.count("contains 'wishlist'"), 4)
        self.assertIn("link.handle contains 'wishlist'", account)
        self.assertIn("const wishlistSelectors", global_script)
        self.assertIn("removeMobileWishlistUI", global_script)
        self.assertIn("mobileWishlistDrawerSelector", global_script)
        self.assertIn("characterData: true", global_script)
        self.assertIn("new MutationObserver", global_script)
        self.assertIn('a[href*="wishlist" i]', stylesheet)
        self.assertIn('[aria-label*="wishlist" i]', stylesheet)
        self.assertEqual(global_script, editor_script)

        for settings in self.sections.values():
            self.assertNotIn("wishlist", json.dumps(settings).lower())

    def test_homepage_collection_eyebrows_use_each_section_accent(self) -> None:
        stylesheet = (
            THEME_ROOT / "assets" / "conversion-theme.css"
        ).read_text(encoding="utf-8")
        eyebrow_rule = stylesheet.split(".sales-collection__eyebrow {", 1)[1].split(
            "}", 1
        )[0]

        self.assertIn("color: var(--section-accent);", eyebrow_rule)

    def test_search_history_is_shared_and_accessible(self) -> None:
        search_script = (
            THEME_ROOT / "assets" / "search-history.js"
        ).read_text(encoding="utf-8")
        editor_search_script = (
            THEME_ROOT / "editor_assets" / "search-history.js"
        ).read_text(encoding="utf-8")
        search_modal = (
            THEME_ROOT / "snippets" / "search-modal.liquid"
        ).read_text(encoding="utf-8")
        header = (THEME_ROOT / "sections" / "header.liquid").read_text(
            encoding="utf-8"
        )

        self.assertEqual(search_script, editor_search_script)
        self.assertIn("data-search-history-form", search_modal)
        self.assertIn('role="combobox"', search_modal)
        self.assertIn('role="listbox"', search_modal)
        self.assertIn("HeaderMobileSearch", header)
        self.assertIn("HeaderDesktopSearch", header)
        self.assertNotIn("searchDropdown", header)
        self.assertNotIn("function clearAll", header)
        self.assertIn("seededHistory.length || localStorage.getItem", search_script)

    def test_component_styles_do_not_depend_on_javascript(self) -> None:
        liquid_files = list(THEME_ROOT.rglob("*.liquid"))
        for path in liquid_files:
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.relative_to(THEME_ROOT)):
                self.assertNotIn(
                    "this.onload=null;this.rel='stylesheet'",
                    text,
                )

    def test_runtime_markup_uses_delegated_actions_and_intrinsic_images(self) -> None:
        event_attribute = re.compile(
            r"\son(?:click|change|submit|keydown|keyup)\s*=",
            re.IGNORECASE,
        )
        image_tag = re.compile(r"<img\b[^>]*>", re.IGNORECASE | re.DOTALL)

        for path in THEME_ROOT.rglob("*.liquid"):
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.relative_to(THEME_ROOT)):
                self.assertIsNone(event_attribute.search(text))
                for tag in image_tag.findall(text):
                    self.assertRegex(tag, r"\bwidth\s*=")
                    self.assertRegex(tag, r"\bheight\s*=")

        global_script = (THEME_ROOT / "assets" / "global.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("const themeActionHandlers", global_script)
        self.assertIn("[data-theme-action]", global_script)

    def test_legacy_jquery_is_replaced_with_compatible_modern_runtime(self) -> None:
        layout = (THEME_ROOT / "layout" / "theme.liquid").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("jquery/1.11", layout)
        self.assertIn("jquery-3.7.1.min.js", layout)
        self.assertIn("jquery-migrate-3.6.0.min.js", layout)
        self.assertEqual(layout.count('integrity="sha256-'), 2)

        for relative in (
            "snippets/repurchase-modal.liquid",
            "templates/customers/order.liquid",
            "templates/customers/orders.liquid",
        ):
            source = (THEME_ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(path=relative):
                self.assertNotIn("$.ajax", source)
                self.assertNotIn("eval(", source)
                self.assertIn("fetch(", source)

    def test_repeated_storefront_labels_use_translation_fallbacks(self) -> None:
        expected = {
            "layout/theme.liquid": "general.search.clear_history",
            "snippets/search-modal.liquid": "general.search.recent_searches",
            "snippets/product-card.liquid": "general.show_details",
            "templates/customers/order.liquid": "customer.addresses.edit",
            "templates/store-locator.liquid": "general.store_locator.hours_unavailable",
        }
        for relative, translation_key in expected.items():
            source = (THEME_ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(path=relative):
                self.assertIn(translation_key, source)
                self.assertIn("| t", source)

    def test_share_widget_instances_have_unique_controls(self) -> None:
        share_snippet = (
            THEME_ROOT / "snippets" / "social-sharing.liquid"
        ).read_text(encoding="utf-8")
        share_script = (THEME_ROOT / "assets" / "share.js").read_text(
            encoding="utf-8"
        )
        editor_share_script = (
            THEME_ROOT / "editor_assets" / "share.js"
        ).read_text(encoding="utf-8")

        self.assertIn("share_instance_id", share_snippet)
        self.assertIn('id="SharePanel-{{ share_instance_id }}"', share_snippet)
        self.assertIn('id="ShareUrl-{{ share_instance_id }}"', share_snippet)
        self.assertNotIn('id="url"', share_snippet)
        self.assertNotIn('id="Product-share-id"', share_snippet)
        self.assertIn("document.execCommand('copy')", share_script)
        self.assertEqual(share_script, editor_share_script)

    def test_customer_order_actions_use_safe_semantics(self) -> None:
        order = (
            THEME_ROOT / "templates" / "customers" / "order.liquid"
        ).read_text(encoding="utf-8")
        orders = (
            THEME_ROOT / "templates" / "customers" / "orders.liquid"
        ).read_text(encoding="utf-8")

        self.assertNotIn("<div onclick=\"window.location.href", orders)
        self.assertIn('<article class="flex-table-tr">', orders)
        self.assertIn('href="/orders/{{ order.cart_token }}/repayment"', orders)
        self.assertIn('data-edit-remark aria-controls="edit-remark"', order)
        self.assertIn('data-edit-payment aria-controls="edit-reference"', order)
        self.assertIn('data-remove-attachment="{{ attachment.id }}"', order)
        self.assertNotIn(".innerHTML +=", order)
        self.assertNotIn(".empty().hide()", order)
        self.assertIn("response.status === 413", order)

    def test_optional_storefront_data_is_defensively_parsed(self) -> None:
        product = (
            THEME_ROOT / "sections" / "main-product.liquid"
        ).read_text(encoding="utf-8")
        store_locator = (
            THEME_ROOT / "templates" / "store-locator.liquid"
        ).read_text(encoding="utf-8")

        self.assertIn("currentViewedProduct.product_id == null", product)
        self.assertIn("productViewHistoryData.slice(0, 20)", product)
        self.assertIn("const parseBusinessHours", store_locator)
        self.assertIn("const dayIndex = new Date().getDay() || 7", store_locator)
        self.assertIn("businessHour.everyday === 'closed'", store_locator)
        self.assertIn("end <= start", store_locator)
        self.assertIn(
            "dropdownToggle.textContent = storeLocatorStrings.hoursUnavailable",
            store_locator,
        )
        self.assertIn("const setHoursStatus", store_locator)
        self.assertNotIn("dropdownToggle.innerHTML", store_locator)

        quickview = (
            THEME_ROOT / "assets" / "product-quickview.js"
        ).read_text(encoding="utf-8")
        editor_quickview = (
            THEME_ROOT / "editor_assets" / "product-quickview.js"
        ).read_text(encoding="utf-8")
        self.assertNotIn("innerHTML +=", quickview)
        self.assertIn("promotionTitle.textContent", quickview)
        self.assertEqual(quickview, editor_quickview)

    def test_default_brand_accent_meets_button_contrast_target(self) -> None:
        preset = self.settings["presets"]["editor"]
        self.assertEqual(preset["colors_accent_1"], "#C44120")
        self.assertEqual(preset["colors_solid_button_labels"], "#FFFFFF")


if __name__ == "__main__":
    unittest.main()
