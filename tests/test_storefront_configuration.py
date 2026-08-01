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

    def test_product_page_media_and_custom_buy_now_checkout_action(self) -> None:
        main_product = (
            THEME_ROOT / "sections" / "main-product.liquid"
        ).read_text(encoding="utf-8")
        self.assertRegex(
            main_product,
            r'name="add"[\s\S]+?class="[^"]*'
            r'product-form__submit--accent-outline[^"]*button--secondary',
        )
        self.assertRegex(
            main_product,
            r'type="button"[\s\S]+?name="buy_now"[\s\S]+?'
            r'data-buy-now[\s\S]+?product-form__buy-now[^"]*button--primary',
        )
        self.assertIn("Buy now", main_product)
        self.assertEqual(
            len(re.findall(r"\sdata-buy-now(?:\s|>)", main_product)),
            1,
        )
        self.assertIn("data-checkout-limit-modal", main_product)
        self.assertIn("data-checkout-limit-message", main_product)
        self.assertIn("data-checkout-limit-cancel", main_product)
        self.assertIn("data-checkout-limit-continue", main_product)
        self.assertIn("Continue without this item?", main_product)
        self.assertIn("Continue to checkout", main_product)
        self.assertRegex(
            main_product,
            r'<form action="/cart" method="post" data-buy-now-checkout-form hidden>'
            r'[\s\S]+?name="_token" value="{% csrf %}"'
            r'[\s\S]+?name="checkout" value="true"',
        )
        self.assertIn("{% app_snippet 'product/button' %}", main_product)
        self.assertIn('class="product-media-video"', main_product)
        self.assertIn('class="product__media-fallback"', main_product)
        self.assertIn("padding: clamp(1.8rem, 4vw, 3rem);", main_product)
        self.assertIn("product.images.size < 2", main_product)
        self.assertIn(
            'class="slider-counter caption" aria-live="polite"',
            main_product,
        )

        product_form = (
            THEME_ROOT / "assets" / "product-form.js"
        ).read_text(encoding="utf-8")
        editor_product_form = (
            THEME_ROOT / "editor_assets" / "product-form.js"
        ).read_text(encoding="utf-8")
        self.assertEqual(product_form, editor_product_form)
        self.assertIn("this.buyNowButton = this.querySelector('[data-buy-now]')", product_form)
        self.assertIn("this.submitProduct(this.buyNowButton, true)", product_form)
        self.assertIn("serializeForm(this.form)", product_form)
        self.assertIn("EasyStore.Action.addToCart", product_form)
        self.assertIn("const minimumItemCount = previousItemCount + requestedQuantity", product_form)
        self.assertIn("itemCount >= minimumItemCount", product_form)
        self.assertIn("latestItems.length > 0", product_form)
        self.assertIn("if (buyNow && !cartConfirmed)", product_form)
        self.assertIn("this.openBuyNowLimitModal(String(cart.description))", product_form)
        self.assertIn("this.openBuyNowLimitModal(", product_form)
        self.assertIn("this.buyNowLimitModal.showModal()", product_form)
        self.assertIn("this.closeBuyNowLimitModal()", product_form)
        self.assertIn(
            "this.checkoutForm = this.querySelector('[data-buy-now-checkout-form]')",
            product_form,
        )
        self.assertEqual(product_form.count("this.goToCheckout();"), 2)
        self.assertIn("this.checkoutForm.requestSubmit()", product_form)
        self.assertIn("this.checkoutForm.submit()", product_form)
        self.assertIn("window.location.assign('/cart')", product_form)
        self.assertNotIn("window.location.assign('/checkout')", product_form)
        self.assertLess(
            product_form.index("if (buyNow && !cartConfirmed)"),
            product_form.rindex("this.goToCheckout();"),
        )

        for asset_directory in ("assets", "editor_assets"):
            stylesheet = (
                THEME_ROOT / asset_directory / "section-main-product.css"
            ).read_text(encoding="utf-8")
            self.assertIn(".product-media-open", stylesheet)
            self.assertIn("aspect-ratio: 1 / 1;", stylesheet)
            self.assertIn("height: min(82vw, 44rem", stylesheet)
            self.assertIn("object-fit: contain;", stylesheet)
            self.assertIn("max-height: calc(100svh - 10rem);", stylesheet)
            self.assertIn(".product-media-open:focus-visible", stylesheet)
            self.assertIn("prefers-reduced-motion: reduce", stylesheet)
            self.assertIn(".product-form__submit--accent-outline", stylesheet)
            self.assertIn(
                "--color-button: var(--color-base-accent-1);",
                stylesheet,
            )
            self.assertIn(
                "--color-button-text: var(--color-base-accent-1);",
                stylesheet,
            )
            self.assertIn("display: grid;", stylesheet)
            self.assertIn("gap: 1.2rem;", stylesheet)
            self.assertIn("min-height: 4.8rem;", stylesheet)
            self.assertIn("margin: 0 !important;", stylesheet)
            self.assertIn("border-radius: 4rem !important;", stylesheet)
            self.assertIn(".product-form__buttons .button::after", stylesheet)
            self.assertIn(".product-form__buttons .btn::after", stylesheet)
            self.assertIn(".buy-now-limit-modal::backdrop", stylesheet)
            self.assertIn(".buy-now-limit-modal__actions", stylesheet)
            self.assertIn("grid-template-columns: 1fr 1fr;", stylesheet)
            self.assertIn("width: min(calc(100% - 3rem), 48rem);", stylesheet)
            self.assertNotIn(".product-form__buy-now", stylesheet)
            self.assertNotIn(".product-form__submit--secondary", stylesheet)

        global_script = (
            THEME_ROOT / "assets" / "global.js"
        ).read_text(encoding="utf-8")
        editor_global_script = (
            THEME_ROOT / "editor_assets" / "global.js"
        ).read_text(encoding="utf-8")
        self.assertEqual(global_script, editor_global_script)
        self.assertIn("this.productForm.querySelector('[data-buy-now]')", global_script)
        self.assertIn("querySelectorAll('.product-form__submit')", global_script)
        self.assertIn("notifyQuantityRules()", global_script)
        self.assertIn("new CustomEvent('product:variant-change'", global_script)

        for relative in (
            "sections/main-product.liquid",
            "sections/featured-product.liquid",
            "snippets/product-quickview.liquid",
        ):
            markup = (THEME_ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(path=relative):
                self.assertIn("data-inventory-quantity", markup)
                self.assertIn("data-quantity-limit-message", markup)
                self.assertIn("aria-live=\"polite\"", markup)

        self.assertIn(
            "{{ 'component-quantity-limit.css' | asset_url | stylesheet_tag }}",
            main_product,
        )
        quickview_modal = (
            THEME_ROOT / "snippets" / "product-quickview-modal.liquid"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "{{ 'component-quantity-limit.css' | asset_url | stylesheet_tag }}",
            quickview_modal,
        )

        self.assertIn("validateQuantity(focusInvalid = false)", product_form)
        self.assertIn("variant.inventory_quantity", product_form)
        self.assertIn("variant.customer_purchase_limit", product_form)
        self.assertIn("variant.store_purchase_limit", product_form)
        self.assertIn("variant.promotion_purchase_limit", product_form)
        self.assertIn("this.nativeQuantityMaximum", product_form)
        self.assertIn("this.quantityInput.setAttribute('max'", product_form)
        self.assertIn("this.setPurchaseButtonsLimited(true)", product_form)
        self.assertIn("this.rememberRejectedQuantity(", product_form)
        self.assertIn("this.validateQuantity(true)", product_form)
        self.assertIn("button.dataset.submissionWasDisabled", product_form)
        self.assertIn("const variantUnavailable", product_form)
        self.assertNotIn(
            "else {\n            button.removeAttribute('disabled');\n"
            "            button.removeAttribute('aria-disabled');",
            product_form,
        )

        layout = (THEME_ROOT / "layout" / "theme.liquid").read_text(
            encoding="utf-8"
        )
        self.assertIn("window.purchaseStrings", layout)
        self.assertIn("products.product.quantity_exceeded", layout)
        self.assertIn("window.purchaseStrings.quantityExceeded", product_form)
        self.assertIn("window.purchaseStrings.quantityMaximum", product_form)
        self.assertIn("window.purchaseStrings.addLimitError", product_form)

        quantity_css = (
            THEME_ROOT / "assets" / "component-quantity-limit.css"
        ).read_text(encoding="utf-8")
        editor_quantity_css = (
            THEME_ROOT / "editor_assets" / "component-quantity-limit.css"
        ).read_text(encoding="utf-8")
        self.assertEqual(quantity_css, editor_quantity_css)
        self.assertIn(".quantity-limit-message--warning", quantity_css)
        self.assertIn(".quantity-limit-message--error", quantity_css)
        self.assertIn(".quantity-limit-exceeded .quantity", quantity_css)
        self.assertIn("prefers-contrast: more", quantity_css)

    def test_reviewed_theme_regressions_are_covered(self) -> None:
        collection_list = (
            THEME_ROOT / "sections" / "collection-list.liquid"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "fetch(`/collections/${CollectionId}/collection_list_section_html",
            collection_list,
        )
        self.assertNotIn(
            "fetch(`collections/${CollectionId}/collection_list_section_html",
            collection_list,
        )

        main_cart = (THEME_ROOT / "sections" / "main-cart.liquid").read_text(
            encoding="utf-8"
        )
        cart_template = (
            THEME_ROOT / "snippets" / "cart-template.liquid"
        ).read_text(encoding="utf-8")
        self.assertIn('id="modal-discount-code"', main_cart)
        self.assertIn('for="modal-discount-code"', main_cart)
        self.assertNotIn('id="input-discount_code"', main_cart)
        self.assertIn('id="input-discount_code"', cart_template)

        header = (THEME_ROOT / "sections" / "header.liquid").read_text(
            encoding="utf-8"
        )
        self.assertIn("function updateReferralData(data)", header)
        self.assertIn("function removeReferralData()", header)
        self.assertEqual(
            header.count("localStorage.setItem('referral_notification_data'"),
            1,
        )
        self.assertEqual(
            header.count("localStorage.removeItem('referral_notification_data'"),
            1,
        )

        self.assertIn("encodeURIComponent(referralCode)", header)
        self.assertIn(
            "const campaign = data && data.data && data.data.campaign;",
            header,
        )
        self.assertIn("Array.isArray(campaign.referral_rules)", header)

        quickview = (
            THEME_ROOT / "assets" / "product-quickview.js"
        ).read_text(encoding="utf-8")
        self.assertIn("this.requestController = new AbortController()", quickview)
        self.assertIn("const requestSequence = ++this.requestSequence", quickview)
        self.assertIn("signal: this.requestController.signal", quickview)
        self.assertIn("requestSequence !== this.requestSequence", quickview)
        self.assertIn("if (this.requestController) this.requestController.abort()", quickview)

        cart = (THEME_ROOT / "assets" / "cart.js").read_text(encoding="utf-8")
        remove_item = cart.split("removeCartItem(line", maxsplit=1)[1]
        self.assertLess(
            remove_item.index("if (!cartItemDeleteBtn) return"),
            remove_item.index("this.enableLoading(line)"),
        )

        social_sharing = (
            THEME_ROOT / "snippets" / "social-sharing.liquid"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "{% assign encoded_permalink_url = permalinkURL | url_param_escape %}",
            social_sharing,
        )
        self.assertIn("media={{ encoded_share_media_url }}", social_sharing)

        customer_details = (
            THEME_ROOT / "templates" / "customers" / "details.liquid"
        ).read_text(encoding="utf-8")
        self.assertIn('max="{{ "now" | date: "%Y-%m-%d" }}"', customer_details)
        self.assertNotIn('date: "%Y%m%d"', customer_details)
        self.assertNotIn('{{ " now" | date:', customer_details)

        layout = (THEME_ROOT / "layout" / "theme.liquid").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'lang="{{ shop.locale | default: \'en\' | escape }}"',
            layout,
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

    def test_header_uses_browse_hierarchy_before_fixed_shortcuts(self) -> None:
        header = (THEME_ROOT / "sections" / "header.liquid").read_text(
            encoding="utf-8"
        )
        browse_snippet = (
            THEME_ROOT / "snippets" / "navigation-browse.liquid"
        )
        self.assertTrue(browse_snippet.exists())
        browse = browse_snippet.read_text(encoding="utf-8")
        self.assertEqual(header.count("navigation-browse"), 2)
        self.assertEqual(header.count("<span>Browse</span>"), 2)
        self.assertIn('class="header__nav-item--browse"', header)
        self.assertIn('class="menu-drawer__nav-item--browse"', header)
        self.assertIn("contents.catalog.links", browse)
        self.assertIn("contents[browse_link.handle].links", browse)
        self.assertIn("contents[child_link.handle].links", browse)
        self.assertIn("contents[grandchild_link.handle].links", browse)
        self.assertIn("great_grandchild_links", browse)
        self.assertIn("great_grandchild_link.url", browse)
        self.assertIn("navigation_mode == 'mobile'", browse)
        self.assertIsNone(
            re.search(
                r"<summary[^>]*>(?:(?!</summary>).)*<a\b",
                browse,
                flags=re.DOTALL,
            )
        )
        self.assertNotIn("{% continue %}", header)
        self.assertEqual(header.count('href="/collections/the-hobbit"'), 2)
        self.assertEqual(
            header.count('href="/collections/marvel-super-heroes"'), 2
        )
        self.assertEqual(
            header.count('href="/collections/secrets-of-strixhaven"'), 2
        )
        self.assertEqual(header.count('href="/pages/about-us"'), 2)

        first_browse = header.index("navigation-browse")
        first_hobbit = header.index('href="/collections/the-hobbit"')
        first_marvel = header.index(
            'href="/collections/marvel-super-heroes"', first_hobbit
        )
        first_strixhaven = header.index(
            'href="/collections/secrets-of-strixhaven"', first_marvel
        )
        first_about = header.index('href="/pages/about-us"', first_strixhaven)
        self.assertLess(first_browse, first_hobbit)
        self.assertLess(first_hobbit, first_marvel)
        self.assertLess(first_marvel, first_strixhaven)
        self.assertLess(first_strixhaven, first_about)

        second_browse = header.index("navigation-browse", first_browse + 1)
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
        self.assertLess(second_browse, second_hobbit)
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
        self.assertIn(
            ".header__nav-item--browse .header__submenu > li",
            stylesheet,
        )
        self.assertIn(".browse-menu__item--has-children:hover", stylesheet)
        self.assertIn(".browse-menu__item--has-children:focus-within", stylesheet)
        self.assertIn(".browse-menu__flyout", stylesheet)
        self.assertIn("left: 100%;", stylesheet)
        self.assertIn("pointer-events: auto;", stylesheet)

        workflow = (
            REPOSITORY_ROOT / ".github" / "workflows" / "package-theme.yml"
        ).read_text(encoding="utf-8")
        self.assertEqual(workflow.count('- "**"'), 2)
        self.assertIn("if: github.event_name != 'pull_request'", workflow)

    def test_unsupported_saved_items_code_is_absent(self) -> None:
        unsupported_term = "wish" + "list"
        for path in THEME_ROOT.rglob("*"):
            if path.is_file():
                self.assertNotIn(
                    unsupported_term,
                    path.read_text(encoding="utf-8").lower(),
                    path,
                )

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
        self.assertIn(
            'integrity="sha256-LWwll4H5AAC/20gH21NFgk4rYMvZhvc1KD0c5iG7QvM="',
            layout,
        )
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
        fallback_snippet = (
            THEME_ROOT / "snippets" / "translation-fallback.liquid"
        ).read_text(encoding="utf-8")
        self.assertIn("translated_value == translation_key", fallback_snippet)
        self.assertIn("translated_value == blank", fallback_snippet)
        self.assertIn("escape_output", fallback_snippet)
        self.assertIn("translated_value | escape", fallback_snippet)

        expected = {
            "layout/theme.liquid": "general.search.clear_history",
            "sections/main-product.liquid": "products.product.buy_now",
            "snippets/search-modal.liquid": "general.search.recent_searches",
            "snippets/product-card.liquid": "general.show_details",
            "templates/customers/order.liquid": "customer.addresses.edit",
            "templates/store-locator.liquid": "general.store_locator.hours_unavailable",
        }
        for relative, translation_key in expected.items():
            source = (THEME_ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(path=relative):
                self.assertIn(translation_key, source)
                self.assertIn("translation-fallback", source)

        broken_fallback = re.compile(r"\|\s*t(?:\s*:[^|}]*)?\s*\|\s*default")
        for path in THEME_ROOT.rglob("*.liquid"):
            source = path.read_text(encoding="utf-8")
            with self.subTest(path=path.relative_to(THEME_ROOT)):
                self.assertIsNone(broken_fallback.search(source))

    def test_liquid_javascript_strings_are_safely_encoded(self) -> None:
        script_pattern = re.compile(
            r"<script(?:\s[^>]*)?>(.*?)</script>", re.IGNORECASE | re.DOTALL
        )
        unsafe_translation = re.compile(r"{{[^{}]*\|\s*t(?:\s*:[^{}]*)?}}")

        for path in THEME_ROOT.rglob("*.liquid"):
            source = path.read_text(encoding="utf-8")
            for script in script_pattern.findall(source):
                for expression in unsafe_translation.findall(script):
                    with self.subTest(path=path.relative_to(THEME_ROOT)):
                        self.assertIn("| json", expression)

        locale = (
            THEME_ROOT / "snippets" / "flatpickr-locale.liquid"
        ).read_text(encoding="utf-8")
        self.assertIn("date_formats.days.sun", locale)
        self.assertIn("date_formats.months.dec", locale)
        self.assertNotRegex(locale, r'"{{[^{}]*\|\s*t')

    def test_async_sections_ignore_stale_requests_and_recover(self) -> None:
        filters = (THEME_ROOT / "snippets" / "filters.liquid").read_text(
            encoding="utf-8"
        )
        self.assertIn("new AbortController()", filters)
        self.assertIn("filterRequestSequence", filters)
        self.assertIn("signal: filterRequestController.signal", filters)
        self.assertIn("error.name === 'AbortError'", filters)

        collection_list = (
            THEME_ROOT / "sections" / "collection-list.liquid"
        ).read_text(encoding="utf-8")
        self.assertIn("if (!response.ok)", collection_list)
        self.assertIn("window.EasyStore?.Currencies", collection_list)
        self.assertNotIn("EasyStore !== undefined", collection_list)
        self.assertIn("previouslyVisibleCollections", collection_list)
        self.assertIn("previousTitle", collection_list)

    def test_repeatable_product_sections_use_scoped_ids(self) -> None:
        featured = (
            THEME_ROOT / "sections" / "featured-product.liquid"
        ).read_text(encoding="utf-8")
        self.assertNotIn('id="AddToCart"', featured)
        self.assertNotIn('id="main-image"', featured)
        self.assertIn('id="AddToCart-{{ section.__key }}"', featured)
        self.assertIn('id="main-image-{{ section.__key }}"', featured)
        self.assertIn('id="image-item-{{ section.__key }}-', featured)
        self.assertIn("if (!variant) return;", featured)

        for asset_directory in ("assets", "editor_assets"):
            quickview = (
                THEME_ROOT / asset_directory / "product-quickview.js"
            ).read_text(encoding="utf-8")
            self.assertIn("window.variantStrings?.quickviewError", quickview)
            self.assertNotIn("window.productStrings?.quickviewError", quickview)
            self.assertIn("if (!variant) return;", quickview)

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
