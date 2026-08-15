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
        self.assertIn("low_inventory_handle contains low_inventory_show_all_handle", snippet)

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

    def test_a_card_counts_down_to_the_threshold(self) -> None:
        for quantity in range(1, THRESHOLD + 1):
            with self.subTest(quantity=quantity):
                rendered = self.card({"available": True, "variants": [variant(quantity)]})
                self.assertIn(f">Only {quantity} left<", rendered)

    def test_a_card_says_nothing_above_the_threshold(self) -> None:
        for quantity in (THRESHOLD + 1, 40):
            with self.subTest(quantity=quantity):
                self.assertEqual(
                    "", self.card({"available": True, "variants": [variant(quantity)]})
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
                    "", self.card({"available": True, "variants": [variant(quantity)]})
                )

    def test_a_sold_out_card_keeps_only_its_badge(self) -> None:
        product = {"available": False, "variants": [variant(0, available=False)]}

        self.assertEqual("", self.card(product))

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

                self.assertEqual("", self.card(product))
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

                self.assertEqual("", self.card(product))

        sold_out = {
            "handle": f"{SHOW_ALL_HANDLE}-ep3",
            "available": False,
            "variants": [variant(40, available=False)],
        }

        self.assertEqual("", self.card(sold_out))

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
