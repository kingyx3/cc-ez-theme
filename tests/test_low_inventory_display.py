"""Checks the remaining-stock notice on product cards and the product page.

Most of this module renders the real snippet, because the mistakes that matter
here are arithmetic rather than markup: counting stock a shopper cannot buy,
claiming a count for a product whose stock is not tracked, or reading a missing
quantity as a number and failing the whole card.

python-liquid is not EasyStore's renderer, so a pass here proves the logic, not
the platform. Verify the counts on a real unpublished theme as well.
"""
from __future__ import annotations

import os
import re
import unittest
from pathlib import Path

try:  # pragma: no cover - exercised by the absence of the dependency
    from liquid import DictLoader, Environment
except ImportError:  # pragma: no cover
    DictLoader = None
    Environment = None

# Skipping is for a developer who has not installed requirements-dev yet. CI
# pins the dependency, so a missing engine there is a broken build.
REQUIRE_ENGINE = bool(os.environ.get("CI"))

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
THEME_ROOT = REPOSITORY_ROOT / "theme"
SNIPPETS = THEME_ROOT / "snippets"
NOTICE = SNIPPETS / "low-inventory-notice.liquid"
PRODUCT_CARD = SNIPPETS / "product-card.liquid"
MAIN_PRODUCT = THEME_ROOT / "sections" / "main-product.liquid"
QUICKVIEW = SNIPPETS / "product-quickview.liquid"
FEATURED_PRODUCT = THEME_ROOT / "sections" / "featured-product.liquid"
LAYOUT = THEME_ROOT / "layout" / "theme.liquid"
THRESHOLD = 5
# Products naming this series print their count at every quantity instead of
# waiting for the threshold.
SHOW_ALL_HANDLE = "late-night-crackers"


def variant(quantity, available: bool = True) -> dict:
    entry = {"available": available}
    if quantity is not None:
        entry["inventory_quantity"] = quantity
    return entry


def listing_variant(quantity, **flags) -> dict:
    """A variant as a collection listing serializes it.

    The product page renders the product EasyStore loads in full, where a
    variant carries `available`. A card renders a product object from a
    collection, and this theme's own card markup reads `is_enabled` from those
    variants while EasyStore names the same idea `is_available` elsewhere. A
    listing variant here therefore carries whichever flag the caller names, and
    none of them by default.
    """
    entry = dict(flags)
    if quantity is not None:
        entry["inventory_quantity"] = quantity
    return entry


class LowInventoryWiringTests(unittest.TestCase):
    def test_product_cards_render_the_notice(self) -> None:
        card = PRODUCT_CARD.read_text(encoding="utf-8")

        self.assertIn("{% include 'price' %}\n        {% include 'low-inventory-notice' %}", card)

    def test_the_product_page_reports_the_selected_variant(self) -> None:
        # A product-level total would contradict the quantity limit beside it,
        # which is enforced per variant.
        section = MAIN_PRODUCT.read_text(encoding="utf-8")

        self.assertIn(
            "{% include 'low-inventory-notice', "
            "low_inventory_variant: product.selected_or_first_available_variant, "
            "low_inventory_persist: true %}",
            section,
        )

    def test_every_surface_with_a_product_form_reports_its_stock(self) -> None:
        # Quick view and the featured-product section render the same form as
        # the product page and reported nothing at all, so a shopper who never
        # opened the product page was told nothing about the stock - including
        # for the series that is meant to print its count at any quantity.
        quickview = QUICKVIEW.read_text(encoding="utf-8")
        featured = FEATURED_PRODUCT.read_text(encoding="utf-8")

        self.assertIn(
            "{% include 'low-inventory-notice', "
            "low_inventory_variant: product.selected_or_first_available_variant, "
            "low_inventory_persist: true %}",
            quickview,
        )
        # This section renders `featured_product`, so it passes the identity to
        # match the series on as a string. The product itself cannot be passed:
        # see test_the_product_object_is_never_assigned_to_a_variable.
        self.assertIn(
            "{% include 'low-inventory-notice', "
            "low_inventory_identity_override: featured_product.handle, "
            "low_inventory_variant: featured_product.selected_or_first_available_variant, "
            "low_inventory_persist: true %}",
            featured,
        )

    def test_no_product_like_object_is_ever_assigned_to_a_variable(self) -> None:
        # Assigning one leaves this snippet reading a page that behaves as
        # though the notice should be hidden even where it has a count to print:
        # every card the lookup answered shipped its count inside a hidden
        # element, while the cards that made no such assignment were fine. The
        # earlier shape of this cost a product page its whole notice.
        #
        # A named object was already forbidden here. A looked-up one -
        # products[handle] - was not, and that is what came back.
        snippet = NOTICE.read_text(encoding="utf-8")

        for name, value in re.findall(r"{%-?\s*assign ([a-z_]+) = ([^%|]+)", snippet):
            value = value.strip()
            self.assertNotIn(
                value,
                ("product", "featured_product", "collection", "cart", "customer"),
                f"{name} is assigned the {value} object",
            )
            # A scalar read out of a lookup is fine - it is a number by the
            # time it lands. The object itself is what must never be kept.
            self.assertNotRegex(
                value,
                r"^(all_products|products|collections)\[[^\]]*\]$",
                f"{name} is assigned a looked-up object: {value}",
            )
        # Objects are read where they are used, and only numbers are kept.
        self.assertNotIn("low_inventory_lookup ", snippet)

    def test_the_markup_reads_one_explicit_comparison(self) -> None:
        # The class, the hidden attribute and the text all key off the same
        # value, so an element can never ship a count inside a hidden span.
        snippet = NOTICE.read_text(encoding="utf-8")
        span = snippet.split("<span class=\"low-inventory-notice", 1)[1].split("</span>", 1)[0]

        self.assertEqual(2, span.count("{% if low_inventory_is_low == false %}"))
        self.assertNotIn("unless", span)

    def test_the_notice_sits_inside_the_form_on_every_surface(self) -> None:
        # product-form.js refreshes the notice through its own subtree, so an
        # element outside <product-form> would freeze on the first variant.
        for source in (
            MAIN_PRODUCT.read_text(encoding="utf-8"),
            QUICKVIEW.read_text(encoding="utf-8"),
            FEATURED_PRODUCT.read_text(encoding="utf-8"),
        ):
            with self.subTest(source=source[:40]):
                form = source.split("<product-form", 1)[1].split("</product-form>", 1)[0]

                self.assertIn("low-inventory-notice", form)

    def test_the_product_page_notice_sits_inside_the_product_form(self) -> None:
        # product-form.js refreshes the notice through its own subtree, so an
        # element outside <product-form> would freeze on the first variant.
        section = MAIN_PRODUCT.read_text(encoding="utf-8")
        form = section.split("<product-form", 1)[1].split("</product-form>", 1)[0]

        self.assertIn("low-inventory-notice", form)

    def test_the_notice_copy_falls_back_when_the_store_has_no_translation(self) -> None:
        snippet = NOTICE.read_text(encoding="utf-8")
        layout = LAYOUT.read_text(encoding="utf-8")

        for source in (snippet, layout):
            self.assertIn("translation_key: 'products.product.low_inventory'", source)
            self.assertIn("fallback: 'Only __COUNT__ left'", source)

        self.assertIn("lowInventory: {{ low_inventory_label | strip | json }},", layout)

    def test_missing_quantities_are_coerced_before_they_are_compared(self) -> None:
        # Liquid raises on `nil > 0` instead of returning false, which would
        # replace the card with an error for any product that reports no count.
        snippet = NOTICE.read_text(encoding="utf-8")

        for expression in re.findall(r"{%-?\s*if [^%]*%}", snippet):
            if ">" not in expression and "<" not in expression:
                continue
            self.assertNotIn(".inventory_quantity", expression, expression)

    def test_the_series_that_prints_every_count_is_configured_in_one_place(self) -> None:
        # One value, matched against the handle, so a new episode or bundle in
        # the series is covered without another edit.
        snippet = NOTICE.read_text(encoding="utf-8")

        self.assertIn(
            f"{{% assign low_inventory_show_all_handle = '{SHOW_ALL_HANDLE}' %}}", snippet
        )
        self.assertIn("low_inventory_identity contains low_inventory_show_all_handle", snippet)

    def test_the_series_is_matched_on_more_than_the_handle(self) -> None:
        # A card is not given the same product object a product page is, so a
        # match that only reads the handle recognised the series on the product
        # page and nowhere else. Every card links to its product, so the link is
        # where the handle is always spelled out.
        snippet = NOTICE.read_text(encoding="utf-8")

        self.assertIn(
            "{{ product.handle }}|{{ low_inventory_url_handle }}|{{ product.sku }}", snippet
        )
        self.assertIn("split: '/products/' | last", snippet)

    def test_include_parameters_are_reset_for_the_next_include(self) -> None:
        # `include` shares one scope: the product page's variant would still be
        # set when the related-product cards below it render.
        snippet = NOTICE.read_text(encoding="utf-8")

        self.assertIn("{% assign low_inventory_variant = null %}", snippet)
        self.assertIn("{% assign low_inventory_persist = null %}", snippet)


class LowInventoryStyleTests(unittest.TestCase):
    RUNTIME = THEME_ROOT / "assets" / "conversion-theme.css"
    EDITOR = THEME_ROOT / "editor_assets" / "conversion-theme.css"

    def test_the_notice_is_styled_by_a_globally_loaded_stylesheet(self) -> None:
        # Cards render on the home, collection, search, 404, and cart pages;
        # conversion-theme.css is loaded by the layout for all of them.
        layout = LAYOUT.read_text(encoding="utf-8")
        self.assertIn("'conversion-theme.css' | asset_url | stylesheet_tag", layout)
        self.assertIn(".low-inventory-notice {", self.RUNTIME.read_text(encoding="utf-8"))

    def test_runtime_and_editor_copies_stay_in_sync(self) -> None:
        self.assertEqual(
            self.RUNTIME.read_text(encoding="utf-8"),
            self.EDITOR.read_text(encoding="utf-8"),
        )


class LowInventoryScriptTests(unittest.TestCase):
    RUNTIME = THEME_ROOT / "assets" / "product-form.js"
    EDITOR = THEME_ROOT / "editor_assets" / "product-form.js"

    def setUp(self) -> None:
        self.source = self.RUNTIME.read_text(encoding="utf-8")

    def test_a_variant_change_refreshes_the_notice(self) -> None:
        self.assertIn("this.updateLowInventoryNotice();", self.source)
        self.assertIn("updateLowInventoryNotice() {", self.source)

    def test_the_notice_is_optional_on_every_other_surface(self) -> None:
        # Quick view and the featured-product section share this component and
        # render no notice; a missing element must not break their forms.
        body = self.source.split("updateLowInventoryNotice() {", 1)[1]
        self.assertIn("if (!notice) return;", body.split("\n\n", 1)[0])

    def test_the_quantity_limit_and_the_notice_read_one_inventory_source(self) -> None:
        self.assertIn("getVariantInventory() {", self.source)
        self.assertEqual(2, self.source.count("this.getVariantInventory()"))
        self.assertEqual(1, self.source.count("dataset.inventoryQuantity"))

    def test_the_threshold_comes_from_the_rendered_markup(self) -> None:
        # One number, defined in the snippet, so the card and the product page
        # cannot disagree about what counts as low.
        self.assertIn("notice.dataset.lowInventoryThreshold", self.source)
        self.assertNotIn("= 5;", self.source)

    def test_a_variant_of_the_configured_series_keeps_printing_its_count(self) -> None:
        # The snippet renders 'all' rather than a number for those products; a
        # script that read it as a number would hide the notice above five units
        # as soon as the shopper picked another variant.
        body = self.source.split("updateLowInventoryNotice() {", 1)[1].split("\n    }", 1)[0]

        self.assertIn("=== 'all'", body)
        self.assertIn("printsEveryCount ||", body)
        self.assertNotIn("!threshold", body)

    def test_runtime_and_editor_copies_stay_in_sync(self) -> None:
        self.assertEqual(self.source, self.EDITOR.read_text(encoding="utf-8"))


@unittest.skipIf(
    Environment is None and not REQUIRE_ENGINE,
    "python-liquid is not installed; run pip install -r requirements-dev.txt",
)
class LowInventoryRenderingTests(unittest.TestCase):
    def setUp(self) -> None:
        if Environment is None:
            self.fail(
                "python-liquid is required in CI: these checks are the only ones "
                "that execute the stock arithmetic the notice prints."
            )

    def render(self, template: str, translation: str = "", **context) -> str:
        loader = DictLoader({
            "low-inventory-notice": NOTICE.read_text(encoding="utf-8"),
            "translation-fallback": (SNIPPETS / "translation-fallback.liquid").read_text(
                encoding="utf-8"
            ),
        })
        environment = Environment(loader=loader)
        environment.filters["t"] = lambda key, *args, **kwargs: translation
        return environment.from_string(template).render(**context)

    def card(self, product: dict, translation: str = "") -> str:
        return self.render(
            "{% include 'low-inventory-notice' %}", translation, product=product
        ).strip()

    def page(self, product: dict) -> str:
        return self.render(
            "{% include 'low-inventory-notice', "
            "low_inventory_variant: product.selected_or_first_available_variant, "
            "low_inventory_persist: true %}",
            product=product,
        ).strip()

    def printed(self, product: dict, translation: str = "") -> str:
        """The text a shopper actually sees.

        The element is always rendered now, so an empty string here means the
        notice is present but hidden, which is what "prints nothing" means.
        """
        rendered = self.card(product, translation)
        if 'hidden="hidden"' in rendered:
            return ""
        return (re.search(r">([^<]*)</span>", rendered) or re.match("", "")).group(1)

    def test_a_card_counts_down_to_the_threshold(self) -> None:
        for quantity in range(1, THRESHOLD + 1):
            with self.subTest(quantity=quantity):
                rendered = self.card({"available": True, "variants": [variant(quantity)]})
                self.assertIn(f">Only {quantity} left<", rendered)

    def test_a_card_says_nothing_above_the_threshold(self) -> None:
        for quantity in (THRESHOLD + 1, 40):
            with self.subTest(quantity=quantity):
                self.assertEqual(
                    "", self.printed({"available": True, "variants": [variant(quantity)]})
                )

    def test_a_card_totals_the_variants_a_shopper_can_buy(self) -> None:
        product = {
            "available": True,
            "variants": [variant(1), variant(3), variant(4, available=False)],
        }

        self.assertIn(">Only 4 left<", self.card(product))

    def test_a_card_claims_no_count_for_untracked_or_missing_stock(self) -> None:
        # Untracked stock is reported the same way as none at all, so a count
        # would be invented rather than read.
        for quantity in (0, None, -2):
            with self.subTest(quantity=quantity):
                self.assertEqual(
                    "", self.printed({"available": True, "variants": [variant(quantity)]})
                )

    def test_a_sold_out_card_keeps_only_its_badge(self) -> None:
        product = {"available": False, "variants": [variant(0, available=False)]}

        self.assertEqual("", self.printed(product))

    def test_a_card_falls_back_to_a_product_level_count(self) -> None:
        product = {"available": True, "variants": [], "inventory_quantity": 2}

        self.assertIn(">Only 2 left<", self.card(product))

    def test_a_configured_card_prints_its_count_at_every_quantity(self) -> None:
        for quantity in (1, THRESHOLD, THRESHOLD + 1, 40):
            with self.subTest(quantity=quantity):
                product = {
                    "handle": f"{SHOW_ALL_HANDLE}-ep3",
                    "available": True,
                    "variants": [variant(quantity)],
                }

                self.assertIn(f">Only {quantity} left<", self.card(product))

    def test_a_configured_handle_is_matched_wherever_the_series_name_falls(self) -> None:
        # Bundles and preorders carry the series name in the middle of their
        # handle, and the series' own handle carries nothing after it.
        for handle in (
            SHOW_ALL_HANDLE,
            f"{SHOW_ALL_HANDLE}-ep4-1",
            f"bundle-{SHOW_ALL_HANDLE}-ep3",
            f"PREORDER-{SHOW_ALL_HANDLE.upper()}-EP5",
        ):
            with self.subTest(handle=handle):
                product = {"handle": handle, "available": True, "variants": [variant(40)]}

                self.assertIn(">Only 40 left<", self.card(product))

    def test_a_product_outside_the_series_keeps_the_threshold(self) -> None:
        for handle in ("MTG-HOB-CBB-EN", "late-night-snacks-ep3", ""):
            with self.subTest(handle=handle):
                product = {"handle": handle, "available": True, "variants": [variant(40)]}

                self.assertEqual("", self.printed(product))
                product["variants"] = [variant(THRESHOLD)]
                self.assertIn(f">Only {THRESHOLD} left<", self.card(product))

    def test_a_configured_card_claims_no_count_for_untracked_or_sold_out_stock(self) -> None:
        # Printing every count is not a licence to invent one: untracked stock
        # is still reported the same way as none at all.
        for quantity in (0, None, -2):
            with self.subTest(quantity=quantity):
                product = {
                    "handle": f"{SHOW_ALL_HANDLE}-ep3",
                    "available": True,
                    "variants": [variant(quantity)],
                }

                self.assertEqual("", self.printed(product))

        sold_out = {
            "handle": f"{SHOW_ALL_HANDLE}-ep3",
            "available": False,
            "variants": [variant(40, available=False)],
        }

        self.assertEqual("", self.printed(sold_out))

    def test_the_product_page_prints_every_count_for_the_configured_series(self) -> None:
        product = {
            "handle": f"{SHOW_ALL_HANDLE}-ep4-2",
            "available": True,
            "variants": [variant(40), variant(2)],
            "selected_or_first_available_variant": variant(40),
        }
        rendered = self.page(product)

        self.assertIn(">Only 40 left<", rendered)
        # The script reads the same attribute after a variant change.
        self.assertIn('data-low-inventory-threshold="all"', rendered)
        self.assertNotIn('hidden="hidden"', rendered)

    def test_a_card_counts_a_variant_that_does_not_carry_available(self) -> None:
        # The listing serialization is what made the notice inconsistent on
        # collection and home pages: a variant that spells availability another
        # way, or not at all, was dropped, so the card printed the product-level
        # total or nothing while the product page printed a count.
        for flags in ({}, {"is_enabled": True}, {"is_available": True}, {"is_enabled": 1}):
            with self.subTest(flags=flags):
                product = {"available": True, "variants": [listing_variant(3, **flags)]}

                self.assertIn(">Only 3 left<", self.card(product))

    def test_a_card_drops_a_variant_whose_flag_reads_false(self) -> None:
        # Dropping is for a flag that says no, in whichever spelling the
        # platform sent, not for a flag the listing did not send.
        for flags in (
            {"available": False},
            {"available": 0},
            {"is_available": False},
            {"is_enabled": False},
            {"is_enabled": 0},
        ):
            with self.subTest(flags=flags):
                product = {"available": True, "variants": [listing_variant(3, **flags)]}

                self.assertEqual("", self.printed(product))

    def test_only_the_first_flag_the_variant_carries_decides(self) -> None:
        # This is what emptied every product page on the store: a variant that
        # reports `available` true alongside an `is_enabled` of 0 was dropped,
        # because a false found anywhere among the three flags dropped it. The
        # flags are not synonyms, so the first one present is the one that
        # answers and the others are not consulted.
        for flags in (
            {"available": True, "is_enabled": 0},
            {"available": True, "is_enabled": False},
            {"available": True, "is_available": False},
            {"available": 1, "is_enabled": 0},
            {"is_available": True, "is_enabled": False},
        ):
            with self.subTest(flags=flags):
                product = {"available": True, "variants": [listing_variant(3, **flags)]}

                self.assertEqual("Only 3 left", self.printed(product))

    def test_a_card_counts_listing_variants_alongside_flagged_ones(self) -> None:
        product = {
            "available": True,
            "variants": [
                listing_variant(1),
                listing_variant(2, is_enabled=True),
                variant(1),
                listing_variant(4, is_enabled=False),
            ],
        }

        self.assertIn(">Only 4 left<", self.card(product))

    def test_a_card_and_its_product_page_agree_on_a_listing_variant(self) -> None:
        # The same stock, read through both surfaces: the card no longer stays
        # silent for a product whose page prints a count.
        product = {
            "available": True,
            "variants": [listing_variant(2, is_enabled=True)],
            "selected_or_first_available_variant": listing_variant(2, is_enabled=True),
        }

        self.assertIn(">Only 2 left<", self.card(product))
        self.assertIn(">Only 2 left<", self.page(product))

    def test_a_card_still_claims_nothing_for_untracked_listing_stock(self) -> None:
        # Counting a variant that did not say no is not the same as inventing a
        # count for one that reports no stock at all.
        for quantity in (0, None, -2):
            with self.subTest(quantity=quantity):
                product = {"available": True, "variants": [listing_variant(quantity)]}

                self.assertEqual("", self.printed(product))

    def test_the_series_is_recognised_from_the_product_link(self) -> None:
        # The failure this fixes: on the product page the handle is there and
        # the count printed at any quantity; on a card whose product arrived
        # without one, the same product read as an ordinary product and printed
        # nothing above five units. The card still links to the product, so the
        # handle is still there to be read.
        for identity in (
            {"url": f"/products/{SHOW_ALL_HANDLE}-ep3"},
            {"url": f"/PRODUCTS/{SHOW_ALL_HANDLE.upper()}-EP3"},
            {"url": f"/products/bundle-{SHOW_ALL_HANDLE}-ep3?variant=8891"},
            {"url": f"/products/{SHOW_ALL_HANDLE}-ep4-1#gallery"},
            {"url": f"/collections/all/products/{SHOW_ALL_HANDLE}-ep4-2"},
            {"sku": f"{SHOW_ALL_HANDLE}-ep3"},
        ):
            with self.subTest(identity=identity):
                product = {"available": True, "variants": [listing_variant(40)], **identity}

                self.assertIn(">Only 40 left<", self.card(product))

    def test_a_series_card_is_matched_through_any_collection_it_is_shown_in(self) -> None:
        # The reported case: the same product, carded in three collections, and
        # the link is the only identifier the card was given.
        for collection in ("marvel-super-heroes", "feature-on-homepage", SHOW_ALL_HANDLE):
            with self.subTest(collection=collection):
                product = {
                    "url": f"/collections/{collection}/products/{SHOW_ALL_HANDLE}-ep3",
                    "available": True,
                    "variants": [listing_variant(40)],
                }

                self.assertIn(">Only 40 left<", self.card(product))

    def test_a_surface_can_pass_the_identity_it_matches_on(self) -> None:
        # The featured-product section renders `featured_product`. It passes the
        # handle as a string, because the product object does not survive being
        # assigned to a variable on EasyStore.
        rendered = self.render(
            "{% include 'low-inventory-notice', "
            "low_inventory_identity_override: featured_product.handle, "
            "low_inventory_variant: featured_product.selected_or_first_available_variant, "
            "low_inventory_persist: true %}",
            featured_product={
                "handle": f"{SHOW_ALL_HANDLE}-ep3",
                "selected_or_first_available_variant": listing_variant(40),
            },
        ).strip()

        self.assertIn(">Only 40 left<", rendered)
        self.assertIn('data-low-inventory-threshold="all"', rendered)

    def test_the_passed_identity_replaces_the_surrounding_product(self) -> None:
        # On that surface `product` is either nothing or the page's own product,
        # which must not decide whether the featured product prints every count.
        rendered = self.render(
            "{% include 'low-inventory-notice', "
            "low_inventory_identity_override: featured_product.handle, "
            "low_inventory_variant: featured_product.selected_or_first_available_variant, "
            "low_inventory_persist: true %}",
            featured_product={
                "handle": "mtg-msh-cbb-en",
                "selected_or_first_available_variant": listing_variant(40),
            },
            product={"handle": f"{SHOW_ALL_HANDLE}-ep3", "url": f"/products/{SHOW_ALL_HANDLE}-ep3"},
        ).strip()

        self.assertIn('data-low-inventory-threshold="5"', rendered)
        self.assertNotIn("Only", rendered)

    def test_the_identity_override_is_reset_for_the_next_include(self) -> None:
        # `include` shares one scope, so an override left set would claim every
        # card rendered after it.
        rendered = self.render(
            "{% include 'low-inventory-notice', "
            "low_inventory_identity_override: featured_handle, "
            "low_inventory_variant: featured_variant, low_inventory_persist: true %}"
            "<hr>"
            "{% include 'low-inventory-notice' %}",
            featured_handle=f"{SHOW_ALL_HANDLE}-ep3",
            featured_variant=listing_variant(40),
            product={"handle": "mtg-msh-cbb-en", "available": True, "variants": [variant(40)]},
        )
        featured, _, card = rendered.partition("<hr>")

        self.assertIn(">Only 40 left<", featured)
        self.assertIn('data-low-inventory-threshold="5"', card)
        self.assertNotIn("Only", card)

    def test_a_link_written_through_the_collection_matches_only_its_product(self) -> None:
        # A card in a collection links within it, so the collection's own handle
        # travels in the URL. Matching the whole URL would have claimed every
        # product shown in the series' collection.
        product = {
            "url": f"/collections/{SHOW_ALL_HANDLE}/products/MTG-HOB-CBB-EN",
            "available": True,
            "variants": [listing_variant(40)],
        }

        self.assertEqual("", self.printed(product))

    def test_a_link_that_names_no_product_is_not_matched_whole(self) -> None:
        for url in (f"/collections/{SHOW_ALL_HANDLE}", f"/pages/{SHOW_ALL_HANDLE}-faq", ""):
            with self.subTest(url=url):
                product = {"url": url, "available": True, "variants": [listing_variant(40)]}

                self.assertEqual("", self.printed(product))

    def test_a_product_outside_the_series_is_not_matched(self) -> None:
        for identity in (
            {"url": "/products/late-night-snacks-ep3"},
            {"url": "/products/crackers"},
            {"handle": "MTG-HOB-CBB-EN", "url": "/products/MTG-HOB-CBB-EN"},
            {},
        ):
            with self.subTest(identity=identity):
                product = {"available": True, "variants": [listing_variant(40)], **identity}

                self.assertEqual("", self.printed(product))

    def test_no_match_is_made_across_two_identifiers(self) -> None:
        # The identifiers are joined, so a value ending one and a value starting
        # the next must not read as the series spanning the join.
        product = {
            "handle": "clearance-late-night",
            "url": "/products/clearance-late-night",
            "sku": "crackers-ep3",
            "available": True,
            "variants": [listing_variant(40)],
        }

        self.assertEqual("", self.printed(product))

    def test_the_configured_series_is_counted_through_the_listing_shape_too(self) -> None:
        product = {
            "handle": f"{SHOW_ALL_HANDLE}-ep4-1",
            "available": True,
            "variants": [listing_variant(40, is_enabled=True)],
        }

        self.assertIn(">Only 40 left<", self.card(product))

    def test_a_store_translation_is_preferred_over_the_fallback_copy(self) -> None:
        rendered = self.card(
            {"available": True, "variants": [variant(2)]}, translation="Tinggal __COUNT__"
        )

        self.assertIn(">Tinggal 2<", rendered)
        self.assertNotIn("Only", rendered)

    def test_the_product_page_reports_the_selected_variant_not_the_total(self) -> None:
        product = {
            "available": True,
            "variants": [variant(3), variant(2)],
            "selected_or_first_available_variant": variant(3),
        }

        self.assertIn(">Only 3 left<", self.page(product))

    def test_the_product_page_counts_a_variant_that_reports_a_disabled_flag(self) -> None:
        # The store's own shape: EasyStore sends the selected variant with
        # `available` true and an `is_enabled` of 0, and every product page
        # rendered its notice empty for a product that had stock.
        product = {
            "handle": "mtg-msh-bgb-en",
            "available": True,
            "variants": [listing_variant(3, available=True, is_enabled=0)],
            "selected_or_first_available_variant": listing_variant(
                3, available=True, is_enabled=0
            ),
        }

        self.assertIn(">Only 3 left<", self.page(product))

    def test_a_starved_card_looks_the_product_up_before_anything_fetches(self) -> None:
        # A collection listing does not always carry stock, and the same product
        # was serialized with it on one page and without it on another. A
        # starved card looks the product up, which costs no request; a store
        # that exposes no such global returns nothing and the card falls back to
        # assets/card-inventory-fill.js.
        snippet = NOTICE.read_text(encoding="utf-8")

        # The variants are kept, never the product: an object in a variable
        # renders a hidden notice around a count, and a lookup written out at
        # each use resolves nothing at all on EasyStore. This is the only route
        # a starved card has - there is no script behind it.
        self.assertIn(
            "{% assign low_inventory_lookup_variants = "
            "products[low_inventory_lookup_handle].variants %}",
            snippet,
        )
        self.assertIn(
            "{% assign low_inventory_lookup_fallback = "
            "all_products[low_inventory_lookup_handle].variants %}",
            snippet,
        )
        # Only when the listing gave nothing, and only within the page's budget.
        self.assertIn(
            "{% if low_inventory_remaining == 0 and low_inventory_lookup_handle != '' "
            "and low_inventory_lookups < 24 %}",
            snippet,
        )

    def test_the_lookup_handle_falls_back_to_the_product_field(self) -> None:
        # The link and the handle field are not populated on the same pages: a
        # card whose link the listing did not carry still has a lookup to make.
        snippet = NOTICE.read_text(encoding="utf-8")

        self.assertIn("{% assign low_inventory_lookup_handle = low_inventory_url_handle %}", snippet)
        self.assertIn(
            "{% assign low_inventory_lookup_handle = product.handle "
            "| default: '' | append: '' | strip | downcase %}",
            snippet,
        )

    def test_the_element_says_which_handle_it_could_look_up(self) -> None:
        # A card that made no lookup is otherwise silent about whether it had a
        # handle to make one with.
        product = {
            "handle": "MTG-HOB-CBB-EN",
            "available": True,
            "variants": [listing_variant(None)],
        }

        self.assertIn('data-low-inventory-handle="mtg-hob-cbb-en"', self.card(product))

    def test_the_page_spends_a_bounded_number_of_lookups(self) -> None:
        # `include` shares one scope, so the counter survives from one card to
        # the next: it is the page's budget, not each card's. Twenty-four covers
        # a full collection grid, and the counter is deliberately not reset with
        # the parameters. Cards past it print nothing.
        snippet = NOTICE.read_text(encoding="utf-8")

        self.assertIn(
            "{% assign low_inventory_lookups = low_inventory_lookups | default: 0 | plus: 0 %}",
            snippet,
        )
        self.assertIn("{% assign low_inventory_lookups = low_inventory_lookups | plus: 1 %}", snippet)
        self.assertNotIn("{% assign low_inventory_lookups = null %}", snippet)

    def test_the_element_says_where_its_count_came_from(self) -> None:
        product = {"available": True, "variants": [listing_variant(3)]}

        self.assertIn('data-low-inventory-source="listing"', self.card(product))

    def test_the_element_carries_the_count_the_snippet_arrived_at(self) -> None:
        # A card that printed nothing is otherwise indistinguishable from a card
        # that was never asked to. The count says which: 0 means the platform
        # sent no stock, and a positive count that printed nothing means the
        # product was not recognised as one that prints at every quantity.
        no_stock = {"available": True, "variants": [listing_variant(None)]}
        above_threshold = {"available": True, "variants": [listing_variant(40)]}

        self.assertIn('data-low-inventory-remaining="0"', self.card(no_stock))
        self.assertIn('data-low-inventory-remaining="40"', self.card(above_threshold))
        # Neither prints anything to a shopper.
        self.assertEqual("", self.printed(no_stock))
        self.assertEqual("", self.printed(above_threshold))

    def test_the_product_page_keeps_a_hidden_element_for_the_next_variant(self) -> None:
        product = {
            "available": True,
            "variants": [variant(40)],
            "selected_or_first_available_variant": variant(40),
        }
        rendered = self.page(product)

        self.assertIn("data-low-inventory-notice", rendered)
        self.assertIn('hidden="hidden"', rendered)
        self.assertIn("low-inventory-notice hidden", rendered)
        self.assertNotIn("Only", rendered)

    def test_the_hidden_element_announces_itself_once_it_is_filled_in(self) -> None:
        product = {
            "available": True,
            "variants": [variant(2)],
            "selected_or_first_available_variant": variant(2),
        }

        self.assertIn('role="status"', self.page(product))

    def test_the_threshold_travels_with_the_markup(self) -> None:
        product = {"available": True, "variants": [variant(2)]}

        self.assertIn(f'data-low-inventory-threshold="{THRESHOLD}"', self.card(product))

    def test_a_card_after_the_product_page_is_not_still_reading_that_variant(self) -> None:
        # The related products below the product page render through the same
        # shared scope. Before the reset they inherited the selected variant and
        # reported its stock as though it were the whole product's.
        product = {
            "available": True,
            "variants": [variant(3)],
            "selected_or_first_available_variant": variant(40),
        }
        rendered = self.render(
            "{% include 'low-inventory-notice', "
            "low_inventory_variant: product.selected_or_first_available_variant, "
            "low_inventory_persist: true %}"
            "<hr>"
            "{% include 'low-inventory-notice' %}",
            product=product,
        )
        page, _, card = rendered.partition("<hr>")

        self.assertNotIn("Only", page)
        self.assertIn(">Only 3 left<", card)
        self.assertNotIn('role="status"', card)


if __name__ == "__main__":
    unittest.main()
