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
THRESHOLD_RESOLVER = SNIPPETS / "low-inventory-threshold.liquid"
THRESHOLD_CONFIG = SNIPPETS / "low-inventory-threshold-config.liquid"
THRESHOLD_ROW = SNIPPETS / "low-inventory-threshold-row.liquid"
PRODUCT_CARD = SNIPPETS / "product-card.liquid"
MAIN_PRODUCT = THEME_ROOT / "sections" / "main-product.liquid"
LAYOUT = THEME_ROOT / "layout" / "theme.liquid"
THRESHOLD = 5
UNLIMITED_FRAGMENT = "late-night-crackers"
UNLIMITED_HANDLE = "late-night-crackers-ep3"


def variant(quantity, available: bool = True, sku: str = None) -> dict:
    entry = {"available": available}
    if quantity is not None:
        entry["inventory_quantity"] = quantity
    if sku is not None:
        entry["sku"] = sku
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
        # One number, resolved by the snippets, so the card and the product page
        # cannot disagree about what counts as low.
        self.assertIn("notice.dataset.lowInventoryThreshold", self.source)
        self.assertNotIn("= 5;", self.source)

    def test_a_product_that_prints_every_count_is_not_hidden_after_a_variant_change(
        self,
    ) -> None:
        # 'all' is not a number, so parsing it as one yields no threshold and the
        # notice the snippet rendered would be cleared on the next variant.
        body = self.source.split("updateLowInventoryNotice() {", 1)[1].split("\n    }", 1)[0]

        self.assertIn("'all'", body)
        self.assertIn("printsEveryCount ||", body)

    def test_runtime_and_editor_copies_stay_in_sync(self) -> None:
        self.assertEqual(self.source, self.EDITOR.read_text(encoding="utf-8"))


class LiquidRendering:
    """Renders the notice and the threshold snippets through python-liquid."""

    def setUp(self) -> None:
        if Environment is None:
            self.fail(
                "python-liquid is required in CI: these checks are the only ones "
                "that execute the stock arithmetic the notice prints."
            )

    def render(self, template: str, translation: str = "", config: str = None, **context) -> str:
        loader = DictLoader({
            "low-inventory-notice": NOTICE.read_text(encoding="utf-8"),
            "low-inventory-threshold": THRESHOLD_RESOLVER.read_text(encoding="utf-8"),
            "low-inventory-threshold-config": (
                THRESHOLD_CONFIG.read_text(encoding="utf-8") if config is None else config
            ),
            "low-inventory-threshold-row": THRESHOLD_ROW.read_text(encoding="utf-8"),
            "translation-fallback": (SNIPPETS / "translation-fallback.liquid").read_text(
                encoding="utf-8"
            ),
        })
        environment = Environment(loader=loader)
        environment.filters["t"] = lambda key, *args, **kwargs: translation
        return environment.from_string(template).render(**context)

    def card(self, product: dict, translation: str = "", config: str = None) -> str:
        return self.render(
            "{% include 'low-inventory-notice' %}",
            translation,
            config=config,
            product=product,
        ).strip()

    def page(self, product: dict, config: str = None) -> str:
        return self.render(
            "{% include 'low-inventory-notice', "
            "low_inventory_variant: product.selected_or_first_available_variant, "
            "low_inventory_persist: true %}",
            config=config,
            product=product,
        ).strip()


@unittest.skipIf(
    Environment is None and not REQUIRE_ENGINE,
    "python-liquid is not installed; run pip install -r requirements-dev.txt",
)
class LowInventoryRenderingTests(LiquidRendering, unittest.TestCase):
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

    def test_an_unlisted_product_keeps_the_shared_default(self) -> None:
        # The shipped configuration names one product; everything else counts
        # down from five, as it did before thresholds were configurable.
        product = {
            "handle": "mtg-hob-pbb-en",
            "available": True,
            "variants": [variant(6, sku="MTG-HOB-PBB-EN")],
        }

        self.assertEqual("", self.card(product))

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


class LowInventoryThresholdConfigurationTests(unittest.TestCase):
    """The configuration file itself: one row per product, and nothing else."""

    def setUp(self) -> None:
        self.config = THRESHOLD_CONFIG.read_text(encoding="utf-8")
        self.row = THRESHOLD_ROW.read_text(encoding="utf-8")
        self.resolver = THRESHOLD_RESOLVER.read_text(encoding="utf-8")

    def test_the_notice_reads_its_threshold_from_the_configuration(self) -> None:
        self.assertIn("{% include 'low-inventory-threshold' %}", NOTICE.read_text(encoding="utf-8"))
        self.assertIn("{% include 'low-inventory-threshold-config' %}", self.resolver)

    def test_the_shared_default_is_a_positive_number(self) -> None:
        # Deleting it would leave every product with a threshold of zero, which
        # prints no count anywhere rather than reverting to the old behaviour.
        match = re.search(
            r"{%\s*assign low_inventory_threshold_default = (\d+)\s*%}", self.config
        )

        self.assertIsNotNone(match, "the configuration must assign a default threshold")
        self.assertEqual(THRESHOLD, int(match.group(1)))

    def test_the_late_night_crackers_series_prints_every_count(self) -> None:
        self.assertIn(
            "{% include 'low-inventory-threshold-row', "
            f"threshold_handle: '*{UNLIMITED_FRAGMENT}*', threshold_maximum: 'all' %}}",
            self.config,
        )

    def test_a_row_clears_its_inputs_for_the_next_row(self) -> None:
        # `include` shares one scope: a row that omits a value would otherwise
        # inherit the previous row's and configure the wrong product.
        self.assertIn("{% assign threshold_handle = '' %}", self.row)
        self.assertIn("{% assign threshold_maximum = '' %}", self.row)


@unittest.skipIf(
    Environment is None and not REQUIRE_ENGINE,
    "python-liquid is not installed; run pip install -r requirements-dev.txt",
)
class LowInventoryThresholdRenderingTests(LiquidRendering, unittest.TestCase):
    """Executes the configuration against products that match its rows."""

    SERIES = "{% include 'low-inventory-threshold-row', threshold_handle: '*late-night-crackers*', threshold_maximum: 'all' %}"

    def config_liquid(self, rows: str, default: int = THRESHOLD) -> str:
        return f"{{% assign low_inventory_threshold_default = {default} %}}\n{rows}\n"

    def test_the_configured_product_prints_a_count_the_whole_way_down(self) -> None:
        product = {
            "handle": UNLIMITED_HANDLE,
            "available": True,
            "variants": [variant(40)],
        }

        self.assertIn(">Only 40 left<", self.card(product))

    def test_the_configured_product_is_matched_by_sku_as_well_as_by_handle(self) -> None:
        # A store that names the series in the SKU rather than in the handle must
        # configure the same product, not a different one.
        product = {
            "handle": "ln-crackers-ep3",
            "available": True,
            "variants": [variant(40, sku="LATE-NIGHT-CRACKERS-EP3")],
        }

        self.assertIn(">Only 40 left<", self.card(product))

    def test_every_product_naming_the_series_is_covered_by_the_one_row(self) -> None:
        # Listing the series rather than each release is the point of the row: an
        # episode that does not exist yet is already configured, and so is a
        # bundle or a preorder that carries the name in the middle of its handle.
        for handle in (
            "late-night-crackers",
            "late-night-crackers-ep3",
            "late-night-crackers-ep11-bundle",
            "bundle-late-night-crackers-ep3",
            "preorder-late-night-crackers-ep5",
        ):
            with self.subTest(handle=handle):
                product = {"handle": handle, "available": True, "variants": [variant(40)]}

                self.assertIn(">Only 40 left<", self.card(product))

    def test_a_product_that_does_not_name_the_series_keeps_the_default(self) -> None:
        for handle in ("late-night-cracker", "mtg-hob-cbb-en-pack", "crackers-late-night"):
            with self.subTest(handle=handle):
                product = {"handle": handle, "available": True, "variants": [variant(40)]}

                self.assertEqual("", self.card(product))

    def test_the_configured_product_publishes_its_threshold_to_the_script(self) -> None:
        product = {
            "handle": UNLIMITED_HANDLE,
            "available": True,
            "variants": [variant(40)],
        }

        self.assertIn('data-low-inventory-threshold="all"', self.card(product))

    def test_the_product_page_prints_every_count_for_the_configured_product(self) -> None:
        product = {
            "handle": UNLIMITED_HANDLE,
            "available": True,
            "variants": [variant(40), variant(9)],
            "selected_or_first_available_variant": variant(40),
        }
        rendered = self.page(product)

        self.assertIn(">Only 40 left<", rendered)
        self.assertNotIn('hidden="hidden"', rendered)

    def test_a_configured_product_still_claims_no_count_for_untracked_stock(self) -> None:
        # 'all' widens the threshold; it does not invent a quantity the platform
        # never reported.
        for quantity in (0, None):
            with self.subTest(quantity=quantity):
                product = {
                    "handle": UNLIMITED_HANDLE,
                    "available": True,
                    "variants": [variant(quantity)],
                }

                self.assertEqual("", self.card(product))

    def test_a_sold_out_configured_product_keeps_only_its_badge(self) -> None:
        product = {
            "handle": UNLIMITED_HANDLE,
            "available": False,
            "variants": [variant(12, available=False)],
        }

        self.assertEqual("", self.card(product))

    def test_a_row_may_set_a_number_instead_of_all(self) -> None:
        config = self.config_liquid(
            "{% include 'low-inventory-threshold-row', "
            "threshold_handle: 'MTG-HOB-PBB-EN', threshold_maximum: 20 %}"
        )
        product = {"handle": "mtg-hob-pbb-en", "available": True, "variants": [variant(18)]}

        self.assertIn(">Only 18 left<", self.card(product, config=config))
        product["variants"] = [variant(21)]
        self.assertEqual("", self.card(product, config=config))
        self.assertIn(
            'data-low-inventory-threshold="20"',
            self.card(
                {"handle": "mtg-hob-pbb-en", "available": True, "variants": [variant(18)]},
                config=config,
            ),
        )

    def test_the_configured_handle_is_matched_whatever_its_case(self) -> None:
        # Both sides are normalized, so a row written the way the product is
        # administered still matches the lowercase storefront handle.
        config = self.config_liquid(
            "{% include 'low-inventory-threshold-row', "
            "threshold_handle: '*Late-Night-Crackers*', threshold_maximum: 'all' %}"
        )
        product = {
            "handle": "LATE-NIGHT-CRACKERS-EP3",
            "available": True,
            "variants": [variant(40)],
        }

        self.assertIn(">Only 40 left<", self.card(product, config=config))

    def test_a_row_without_a_wildcard_still_matches_the_whole_handle_only(self) -> None:
        # A box and a single pack are separate products whose handles share a
        # prefix; without the '*' a row must claim neither of the other's stock.
        config = self.config_liquid(
            "{% include 'low-inventory-threshold-row', "
            "threshold_handle: 'MTG-HOB-CBB-EN', threshold_maximum: 'all' %}"
        )

        self.assertEqual(
            "",
            self.card(
                {
                    "handle": "mtg-hob-cbb-en-pack",
                    "available": True,
                    "variants": [variant(40)],
                },
                config=config,
            ),
        )
        self.assertIn(
            ">Only 40 left<",
            self.card(
                {"handle": "mtg-hob-cbb-en", "available": True, "variants": [variant(40)]},
                config=config,
            ),
        )

    def test_each_wildcard_position_drops_only_that_anchor(self) -> None:
        # 'crackers' names the end of one handle and the middle of the other, so
        # each form is only claimed by the rows that reach that far.
        cases = {
            # row handle          crackers  crackers-ep3  late-night-crackers  late-night-crackers-ep3
            "crackers": (True, False, False, False),
            "crackers*": (True, True, False, False),
            "*crackers": (True, False, True, False),
            "*crackers*": (True, True, True, True),
        }
        handles = ("crackers", "crackers-ep3", "late-night-crackers", "late-night-crackers-ep3")
        cases = {row: dict(zip(handles, expected)) for row, expected in cases.items()}
        for row_handle, expectations in cases.items():
            config = self.config_liquid(
                "{% include 'low-inventory-threshold-row', "
                f"threshold_handle: '{row_handle}', threshold_maximum: 'all' %}}"
            )
            for product_handle, matches in expectations.items():
                with self.subTest(row_handle=row_handle, product_handle=product_handle):
                    product = {
                        "handle": product_handle,
                        "available": True,
                        "variants": [variant(40)],
                    }
                    rendered = self.card(product, config=config)

                    if matches:
                        self.assertIn(">Only 40 left<", rendered)
                    else:
                        self.assertEqual("", rendered)

    def test_an_unusable_wildcard_is_ignored_rather_than_claiming_every_product(self) -> None:
        # A bare '*' would match every identifier in the store, and a '*' left in
        # the middle can never appear in a handle, so neither row is kept. The
        # third case is the one that matters: dropping the row is not the same as
        # ignoring the '*', which would quietly claim the product it spells out.
        for row_handle in ("*", "**", "late-night-crackers*-ep3"):
            with self.subTest(row_handle=row_handle):
                config = self.config_liquid(
                    "{% include 'low-inventory-threshold-row', "
                    f"threshold_handle: '{row_handle}', threshold_maximum: 'all' %}}"
                )
                product = {
                    "handle": "late-night-crackers-ep3",
                    "available": True,
                    "variants": [variant(40)],
                }

                self.assertEqual("", self.card(product, config=config))

    def test_the_first_matching_row_wins(self) -> None:
        config = self.config_liquid(
            "{% include 'low-inventory-threshold-row', "
            "threshold_handle: 'late-night-crackers-ep3', threshold_maximum: 8 %}\n"
            + self.SERIES
        )
        product = {
            "handle": UNLIMITED_HANDLE,
            "available": True,
            "variants": [variant(40)],
        }

        self.assertEqual("", self.card(product, config=config))

    def test_an_unusable_row_leaves_the_product_on_the_default(self) -> None:
        # A typo must not hide a notice that was showing before the row was added.
        for maximum in ("''", "0", "'evrything'", "-3"):
            with self.subTest(maximum=maximum):
                config = self.config_liquid(
                    "{% include 'low-inventory-threshold-row', "
                    f"threshold_handle: '*late-night-crackers*', threshold_maximum: {maximum} %}}"
                )
                product = {
                    "handle": UNLIMITED_HANDLE,
                    "available": True,
                    "variants": [variant(3)],
                }

                self.assertIn(">Only 3 left<", self.card(product, config=config))

    def test_a_configured_product_does_not_leak_its_threshold_to_the_next_card(self) -> None:
        # Cards render in a loop through one shared scope, so the series' 'all'
        # must not follow the card rendered after it.
        rendered = self.render(
            "{% include 'low-inventory-notice' %}<hr>"
            "{% assign product = other %}{% include 'low-inventory-notice' %}",
            product={
                "handle": UNLIMITED_HANDLE,
                "available": True,
                "variants": [variant(40)],
            },
            other={"handle": "mtg-hob-pbb-en", "available": True, "variants": [variant(40)]},
        )
        pack, _, other = rendered.partition("<hr>")

        self.assertIn(">Only 40 left<", pack)
        self.assertEqual("", other.strip())


if __name__ == "__main__":
    unittest.main()
