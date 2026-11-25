from __future__ import annotations

import json
import os
import re
import unittest
from pathlib import Path

try:  # pragma: no cover - exercised by the absence of the dependency
    from liquid import DictLoader, Environment
except ImportError:  # pragma: no cover
    DictLoader = None
    Environment = None


ROOT = Path(__file__).resolve().parents[2]
THEME = ROOT / "theme"
SNIPPETS = THEME / "snippets"
# Skipping is for a developer who has not installed requirements-dev yet; in CI
# the engine is pinned, so a missing one is a broken build.
REQUIRE_ENGINE = bool(os.environ.get("CI"))

# The Star Trek exclusive add-ons are separate listings from the products they
# duplicate, each with its own per-order limit. Rows key on the product handle
# because that is what every add-to-cart, Buy Now and checkout check looks up.
TRK_BUNDLE_ADDON = "exclusive-add-on-mtg-star-trek-beam-me-up-bundle"
TRK_COMBO_ADDON = "exclusive-add-on-mtg-star-trek-play-booster-box-plus-beam-me-up-bundle-combo"
# The originals carry no per-order limit, and adding the add-ons must not give
# them one.
TRK_ORIGINALS = ("mtg-trk-bmb-en", "cc-bdl-trk-beammeupandplay-en")

# Vault Break (Black Friday 2026) per-order limits from Berne's brief: the
# Marvel Super Heroes Prerelease Kit at 2 per order and the Foundations
# Commander Set of 5 at 1 per order. Keyed on product handle.
MSH_PRERELEASE_KIT = "mtg-msh-prk-en"
FDN_COMMANDER_SET5 = "mtg-fdn-cmd-en-set5"
# The Foundations singles are separate listings and get no limit from the set.
FDN_COMMANDER_SINGLES = tuple(
    f"mtg-foundations-commander-deck-{deck}"
    for deck in (
        "calling-all-angels",
        "keen-engineering",
        "wretched-ranks",
        "reign-of-dragons",
        "tramplesaurus-rex",
    )
)


class PerOrderLimitTests(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (THEME / relative).read_text(encoding="utf-8")

    def test_per_order_configuration_is_separate_from_customer_limits(self) -> None:
        customer = self.read("snippets/customer-order-limit-config.liquid")
        currencies = self.read("snippets/currencies.liquid")
        order = self.read("snippets/per-order-limit-config.liquid")

        self.assertNotIn("per-order-limit", customer)
        self.assertIn("{% include 'customer-order-limits' %}", currencies)
        self.assertIn("{% include 'per-order-limits' %}", currencies)
        self.assertIn("separate from customer-order-limit-config.liquid", order)
        self.assertIn("order_limit_handle", order)
        self.assertIn("order_limit_maximum", order)
        self.assertIn("A single row is the whole configuration change", order)
        self.assertNotIn("limit_refresh", order)
        self.assertNotIn("wildcard", order.lower())

    def test_one_exact_row_is_the_whole_change_for_a_new_handle(self) -> None:
        config = self.read("snippets/per-order-limit-config.liquid")
        row = self.read("snippets/per-order-limit-row.liquid")

        example = (
            "{% include 'per-order-limit-row', order_limit_handle: "
            "'MTG-HOB-CBB-EN', order_limit_maximum: 1 %}"
        )
        nauctis_promo = (
            "{% include 'per-order-limit-row', order_limit_handle: "
            "'mtg-nauctis-preorder', order_limit_maximum: 1 %}"
        )
        self.assertIn(example, config)
        # The Foundations Keen Engineering single (SKU MTG-FDN-CMD-EN-U) has no
        # per-order limit; only the Set of 5 does.
        self.assertNotIn("'mtg-fdn-cmd-en-u'", config.lower())
        self.assertIn(nauctis_promo, config)
        self.assertNotIn("mystery-booster-commander-edition-booster-pack", config)
        self.assertIn("Adding or changing an order limit is one row", row)
        self.assertIsNone(re.search(r"per_order_limit_\w*_\d", row))
        self.assertIsNone(re.search(r"order_limit_(handle|maximum)_\d", config))
        self.assertIn("{% assign order_limit_handle = '' %}", row)
        self.assertIn("{% assign order_limit_maximum = 0 %}", row)

    def test_cart_is_scanned_once_for_all_order_rows(self) -> None:
        bootstrap = self.read("snippets/per-order-limits.liquid")
        row = self.read("snippets/per-order-limit-row.liquid")

        self.assertEqual(bootstrap.count("{% for cart_item in cart.items %}"), 1)
        self.assertIn("cart_item.product.handle", bootstrap)
        self.assertIn("cart_item.sku", bootstrap)
        self.assertIn("window.perOrderLimitsV1 = { rules: {}, cart: {} }", bootstrap)
        self.assertIn("{% include 'per-order-limit-config' %}", bootstrap)
        self.assertIn("per-order-limits.js", bootstrap)
        self.assertNotIn("{% for cart_item in cart.items %}", row)
        self.assertIn("window.perOrderLimitsV1.rules", row)
        self.assertIn("maximum:", row)
        self.assertIn("cartQuantity: window.perOrderLimitsV1.cart", row)

    def test_order_validator_is_independent_and_layered_with_customer_validator(self) -> None:
        storefront = self.read("assets/per-order-limits.js")
        editor = self.read("editor_assets/per-order-limits.js")

        self.assertEqual(storefront, editor)
        for expected in (
            "per order",
            "quantityLimitForHandle",
            "additionViolation",
            "cartViolationFromForm",
            "recordAddition",
            "recordRemoval",
            "perOrderLimitsWrapped",
            "strictest",
            "[data-buy-now]",
            "name !== 'expresscheckout'",
        ):
            self.assertIn(expected, storefront)

        self.assertNotIn("loadHistory", storefront)
        self.assertNotIn("HISTORY_URL", storefront)
        self.assertNotIn("redirectToLogin", storefront)

    def test_star_trek_add_ons_are_limited_per_order_by_handle(self) -> None:
        config = self.read("snippets/per-order-limit-config.liquid")

        for handle, maximum in ((TRK_BUNDLE_ADDON, 4), (TRK_COMBO_ADDON, 6)):
            with self.subTest(handle=handle):
                self.assertIn(
                    "{% include 'per-order-limit-row', order_limit_handle: "
                    f"'{handle}', order_limit_maximum: {maximum} %}}",
                    config,
                )
        for handle in TRK_ORIGINALS:
            with self.subTest(handle=handle):
                self.assertNotIn(f"'{handle}'", config.lower())

        # tests/e2e/per-order-limit-config.spec.js runs these rows through the
        # real validator; it only guards anything if CI runs it.
        workflow = (ROOT / ".github/workflows/e2e-theme.yml").read_text(encoding="utf-8")
        self.assertIn("tests/e2e/per-order-limit-config.spec.js", workflow)

    def test_vault_break_kit_and_foundations_set_are_limited_per_order_by_handle(self) -> None:
        config = self.read("snippets/per-order-limit-config.liquid")

        for handle, maximum in ((MSH_PRERELEASE_KIT, 2), (FDN_COMMANDER_SET5, 1)):
            with self.subTest(handle=handle):
                self.assertIn(
                    "{% include 'per-order-limit-row', order_limit_handle: "
                    f"'{handle}', order_limit_maximum: {maximum} %}}",
                    config,
                )
        for handle in FDN_COMMANDER_SINGLES:
            with self.subTest(handle=handle):
                self.assertNotIn(f"'{handle}'", config.lower())


@unittest.skipIf(
    Environment is None and not REQUIRE_ENGINE,
    "python-liquid is not installed; run pip install -r requirements-dev.txt",
)
class PerOrderLimitRenderingTests(unittest.TestCase):
    """Renders the shipped per-order config and reads the rules it publishes.

    python-liquid is not EasyStore's renderer, so this proves the rows and the
    cart pass, not the platform.
    """

    def setUp(self) -> None:
        if Environment is None:
            self.fail("python-liquid is required in CI to render the limit snippets.")

    def render(self, cart_items: list) -> tuple[dict, dict]:
        files = {
            name: (SNIPPETS / f"{name}.liquid").read_text(encoding="utf-8")
            for name in ("per-order-limits", "per-order-limit-row", "per-order-limit-config")
        }
        environment = Environment(loader=DictLoader(files))
        environment.filters["json"] = json.dumps
        environment.filters["asset_url"] = lambda value: f"/assets/{value}"
        output = environment.get_template("per-order-limits").render(cart={"items": cart_items})

        maximums = {
            json.loads(match.group(1)): int(match.group(2))
            for match in re.finditer(
                r"window\.perOrderLimitsV1\.rules\[(\".*?\")\] = \{\s*maximum: (\d+),", output
            )
        }
        cart: dict = {}
        for match in re.finditer(
            r"window\.perOrderLimitsV1\.cart\[(\".*?\")\] = \(.*?\) \+ (\d+);", output
        ):
            key = json.loads(match.group(1))
            cart[key] = cart.get(key, 0) + int(match.group(2))
        return maximums, cart

    def test_star_trek_add_ons_publish_independent_limits(self) -> None:
        maximums, cart = self.render([
            {"product": {"handle": TRK_BUNDLE_ADDON}, "sku": "MTG-TRK-BMB-EN-ADDON", "quantity": 4},
            {"product": {"handle": TRK_COMBO_ADDON}, "sku": "CC-BDL-TRK-BEAMMEUPANDPLAY-EN-ADDON", "quantity": 6},
            {"product": {"handle": "mtg-trk-bmb-en"}, "sku": "MTG-TRK-BMB-EN", "quantity": 9},
        ])

        self.assertEqual(maximums[TRK_BUNDLE_ADDON], 4)
        self.assertEqual(maximums[TRK_COMBO_ADDON], 6)
        # Each add-on's cart count is its own lines only.
        self.assertEqual(cart[TRK_BUNDLE_ADDON], 4)
        self.assertEqual(cart[TRK_COMBO_ADDON], 6)
        for handle in TRK_ORIGINALS:
            with self.subTest(handle=handle):
                self.assertNotIn(handle, maximums)

    def test_vault_break_rows_publish_independent_limits(self) -> None:
        maximums, cart = self.render([
            {"product": {"handle": MSH_PRERELEASE_KIT}, "sku": "MTG-MSH-PRK-EN", "quantity": 2},
            {"product": {"handle": FDN_COMMANDER_SET5}, "sku": "MTG-FDN-CMD-EN-SET5", "quantity": 1},
            {"product": {"handle": FDN_COMMANDER_SINGLES[3]}, "sku": "MTG-FDN-CMD-EN-R", "quantity": 3},
        ])

        self.assertEqual(maximums[MSH_PRERELEASE_KIT], 2)
        self.assertEqual(maximums[FDN_COMMANDER_SET5], 1)
        self.assertEqual(cart[MSH_PRERELEASE_KIT], 2)
        self.assertEqual(cart[FDN_COMMANDER_SET5], 1)
        for handle in FDN_COMMANDER_SINGLES:
            with self.subTest(handle=handle):
                self.assertNotIn(handle, maximums)

    def test_every_configured_row_publishes_one_rule(self) -> None:
        maximums, _ = self.render([])
        config = (SNIPPETS / "per-order-limit-config.liquid").read_text(encoding="utf-8")
        configured = re.findall(
            r"^\{% include 'per-order-limit-row', order_limit_handle: '([^']+)', "
            r"order_limit_maximum: (\d+) %\}$",
            config,
            re.M,
        )

        self.assertEqual(
            maximums, {handle.lower(): int(maximum) for handle, maximum in configured}
        )


if __name__ == "__main__":
    unittest.main()
