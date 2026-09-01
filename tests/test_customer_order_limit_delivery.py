"""Performance guardrails for purchase-limit delivery.

The storefront must not re-walk a signed-in customer's order history once per
configured product before returning every page. The client validator already
has an authoritative, cached account-history loader and blocks a purchase while
that history is unresolved, so storefront delivery deliberately opts into that
path while direct snippet rendering keeps the original inline behavior.
"""
from __future__ import annotations

import json
import os
import re
import unittest
from pathlib import Path

try:  # pragma: no cover - exercised when local dev deps are absent
    from liquid import DictLoader, Environment
except ImportError:  # pragma: no cover
    DictLoader = None
    Environment = None


ROOT = Path(__file__).resolve().parents[1]
THEME = ROOT / "theme"
SNIPPETS = THEME / "snippets"
REQUIRE_ENGINE = bool(os.environ.get("CI"))
HANDLE = "mtg-hob-scn-en-set2"


def read(relative: str) -> str:
    return (THEME / relative).read_text(encoding="utf-8")


class StorefrontDeliveryShapeTests(unittest.TestCase):
    def test_currencies_opts_storefront_into_deferred_history(self) -> None:
        currencies = read("snippets/currencies.liquid")
        self.assertIn(
            "{% include 'customer-order-limits', defer_history: true %}",
            currencies,
        )

    def test_both_server_history_passes_obey_the_inline_history_switch(self) -> None:
        limits = read("snippets/customer-order-limits.liquid")
        row = read("snippets/customer-order-limit-row.liquid")

        self.assertIn("{% if defer_history %}", limits)
        self.assertIn(
            "{% if customer_order_limit_customer_authenticated and "
            "customer_order_limit_inline_history_enabled %}",
            limits,
        )
        self.assertIn(
            "{% if customer_order_limit_customer_authenticated and "
            "customer_order_limit_inline_history_enabled %}",
            row,
        )


@unittest.skipIf(
    Environment is None and not REQUIRE_ENGINE,
    "python-liquid is not installed; run pip install -r requirements-dev.txt",
)
class DeferredHistoryRenderingTests(unittest.TestCase):
    def setUp(self) -> None:
        if Environment is None:
            self.fail("python-liquid is required in CI")

        files = {
            name: (SNIPPETS / f"{name}.liquid").read_text(encoding="utf-8")
            for name in (
                "customer-order-limit-window",
                "customer-order-limit-cancelled",
                "customer-order-limit-rule",
                "customer-order-limit-row",
                "customer-order-limits",
            )
        }
        files["customer-order-limit-config"] = (
            "{% assign customer_order_limit_refresh_all = "
            "'2026-08-09 00:00:00 +0000' %}\n"
            "{% include 'customer-order-limit-row', "
            "limit_handle: 'MTG-HOB-SCN-EN-SET2', limit_maximum: 2, "
            "limit_refresh: '' %}\n"
        )
        self.environment = Environment(loader=DictLoader(files))
        self.environment.filters["json"] = json.dumps
        self.environment.filters["asset_url"] = lambda value: f"/assets/{value}"

    def render(self, *, defer_history: bool) -> str:
        return self.environment.get_template("customer-order-limits").render(
            defer_history=defer_history,
            customer={
                "id": 42,
                "email": "buyer@example.com",
                "orders": [{
                    "created_at": "2026-08-20 12:00:00 +0000",
                    "is_cancelled": 0,
                    "line_items": [{
                        "sku": "MTG-HOB-SCN-EN-SET2",
                        "quantity": 1,
                    }],
                }],
            },
            cart={"items": []},
            product=None,
        )

    def purchased(self, output: str) -> int:
        rule = re.search(
            rf"rules\[\"{re.escape(HANDLE)}\"\] = \{{(.*?)\n    \}};",
            output,
            re.S,
        )
        self.assertIsNotNone(rule)
        value = re.search(r"purchased: (\d+)", rule.group(1))
        self.assertIsNotNone(value)
        return int(value.group(1))

    def lines_seen(self, output: str) -> int:
        value = re.search(r"lineItemsSeen: (\d+)", output)
        self.assertIsNotNone(value)
        return int(value.group(1))

    def test_deferred_storefront_render_does_not_count_inline_history(self) -> None:
        rendered = self.render(defer_history=True)

        self.assertEqual(self.purchased(rendered), 0)
        self.assertEqual(self.lines_seen(rendered), 0)

    def test_default_render_keeps_existing_inline_history_behavior(self) -> None:
        rendered = self.render(defer_history=False)

        self.assertEqual(self.purchased(rendered), 1)
        self.assertEqual(self.lines_seen(rendered), 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
