from __future__ import annotations

import json
import re
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:  # pragma: no cover - exercised by the absence of the dependency
    from liquid import DictLoader, Environment
except ImportError:  # pragma: no cover
    DictLoader = None
    Environment = None

import os


ROOT = Path(__file__).resolve().parents[1]
THEME = ROOT / "theme"
SNIPPETS = THEME / "snippets"
NOW = datetime.now(timezone.utc)
HANDLE = "MTG-HOB-SCN-EN-SET2"
LOWER = HANDLE.lower()
REQUIRE_ENGINE = bool(os.environ.get("CI"))


class HistoryPayloadStructureTests(unittest.TestCase):
    """The account order page publishes history for pages that cannot see it."""

    def read(self, relative: str) -> str:
        return (THEME / relative).read_text(encoding="utf-8")

    def test_the_account_order_page_publishes_the_payload(self) -> None:
        orders = self.read("templates/customers/orders.liquid")

        # This template demonstrably has line items — it renders them — so it is
        # the source of truth for pages that receive orders without them.
        self.assertIn("{% include 'customer-order-limit-history' %}", orders)
        self.assertIn("{% for order in customer.orders %}", orders)
        self.assertIn("order.line_items", orders)

    def test_payload_is_json_in_a_stable_element(self) -> None:
        history = self.read("snippets/customer-order-limit-history.liquid")

        self.assertIn('<script type="application/json" id="customer-order-limit-history">', history)
        self.assertIn('"lines":[', history)
        self.assertIn('"customer":', history)
        self.assertIn('"truncated":', history)
        # Cancelled orders and unreadable dates follow the same rules as the
        # inline pass, and the line cap keeps the payload bounded.
        self.assertIn("{%- unless order.is_cancelled -%}", history)
        self.assertIn("order.created_at | date: '%s' | plus: 0", history)
        self.assertIn("order.line_items | default: order.items", history)
        self.assertIn("customer_order_limit_history_count >= 500", history)
        # No filtering by handle here: the reading page applies its own config.
        self.assertNotIn("customer_order_limit_handle_1", history)
        # The list is tab filtered and paginated, so the reader needs to know
        # which tabs hold orders and where the next page is. A live store
        # returned zero lines because the default tab held none.
        self.assertIn('"currentTab":', history)
        self.assertIn('"tabs":[', history)
        self.assertIn('"pages":', history)
        self.assertIn('"nextUrl":', history)
        self.assertIn("customer.paginate.filter.tabs", history)
        self.assertIn("paginate.next.url", history)
        # Each line carries its order token so the same line seen under two tabs
        # is counted once.
        self.assertIn("customer_order_limit_history_token", history)

    def test_liquid_booleans_are_read_by_value_not_by_identity(self) -> None:
        limits = self.read("assets/customer-order-limits.js")

        # EasyStore's json filter renders a Liquid boolean as 1 or 0, so a strict
        # `=== true` read of the sign-in flag is false for a signed-in customer.
        self.assertIn("const truthy = (value) => (", limits)
        self.assertIn("value === true || value === 1 || value === '1' || value === 'true'", limits)
        self.assertIn("const customerAuthenticated = truthy(source.customerAuthenticated);", limits)
        self.assertNotIn("source.customerAuthenticated === true", limits)

    def test_the_console_check_survives_an_older_published_build(self) -> None:
        snippet = (ROOT / "scripts" / "limit-check.console.js").read_text(encoding="utf-8")

        # It crashed on a build without the history loader instead of reporting
        # that the published theme was out of date.
        self.assertIn("typeof api.historyState === 'function'", snippet)
        self.assertIn("typeof api.loadHistory === 'function'", snippet)
        self.assertIn("BUILD IS OLD", snippet)
        self.assertIn("CANNOT TELL", snippet)
        # The load is only attempted when the build can do it.
        self.assertIn("if (hasHistoryLoader && (state() === 'unknown'", snippet)

    def test_rules_publish_the_window_start_for_client_filtering(self) -> None:
        rule = self.read("snippets/customer-order-limit-rule.liquid")
        limits = self.read("snippets/customer-order-limits.liquid")

        self.assertIn("windowStart: {{ customer_order_limit_rule_window_start | json }},", rule)
        self.assertEqual(limits.count("rule_window_start: customer_order_limit_window_"), 14)
        self.assertIn("customerId: {{ customer_order_limit_customer_id | json }},", limits)

    def test_validator_loads_history_and_holds_purchases_until_it_knows(self) -> None:
        limits = self.read("assets/customer-order-limits.js")

        self.assertIn("const HISTORY_URL = '/account/orders';", limits)
        self.assertIn("const HISTORY_PAYLOAD_ID = 'customer-order-limit-history';", limits)
        # Only line items actually read count as history: assuming "no orders"
        # is what let the limit lapse.
        self.assertIn(
            "const inlineHistoryRead = quantity(diagnostics.lineItemsSeen, 0) > 0;",
            limits,
        )
        # A purchase attempted before history is known is held, never measured
        # against an allowance that assumes nothing was bought.
        self.assertEqual(limits.count("historyBlocks("), 4)
        self.assertIn("const HISTORY_PENDING_MESSAGE =", limits)
        # Failure must fall open rather than block selling.
        self.assertIn("historyState = 'unavailable';", limits)
        self.assertIn("    if (historySupported()) loadHistory();", limits)
        # Guests are never fetched for, and the window is applied client-side.
        self.assertIn("quantity(rule && rule.windowStart, 0)", limits)
        # loadHistory runs at the end of page setup, so a browser without fetch
        # or DOMParser must degrade instead of throwing from there or from a
        # purchase handler.
        # Every tab that reports orders is walked, following pagination, with a
        # request cap and de-duplication by order token.
        self.assertIn("const HISTORY_MAX_REQUESTS = 12;", limits)
        self.assertIn("const historyUrlsFrom = (payload, fetched) => {", limits)
        self.assertIn("if (/cancel/i.test(status)) return;", limits)
        self.assertIn("if (quantity(tab.count, 0) === 0) return;", limits)
        self.assertIn("const key = line.slice(0, 5).join('|');", limits)
        self.assertIn("const historySupported = () => (", limits)
        self.assertIn("typeof fetch === 'function'", limits)
        self.assertIn("typeof DOMParser === 'function'", limits)
        self.assertIn("if (shopperSignedOut() || !historySupported()) {", limits)
        self.assertIn("    } catch (_error) {\n      historyState = 'unavailable';", limits)
        self.assertIn("else historyState = 'unavailable';", limits)
        self.assertEqual(limits, self.read("editor_assets/customer-order-limits.js"))


@unittest.skipIf(
    Environment is None and not REQUIRE_ENGINE,
    "python-liquid is not installed; run pip install -r requirements-dev.txt",
)
class HistoryPayloadRenderingTests(unittest.TestCase):
    """Renders the payload and the product-page pass with the failing shape."""

    def setUp(self) -> None:
        if Environment is None:
            self.fail("python-liquid is required in CI")

    def environment(self):
        files = {
            name: (SNIPPETS / f"{name}.liquid").read_text(encoding="utf-8")
            for name in (
                "customer-order-limit-config",
                "customer-order-limit-window",
                "customer-order-limit-rule",
                "customer-order-limits",
                "customer-order-limit-history",
            )
        }
        environment = Environment(loader=DictLoader(files))
        environment.filters["json"] = json.dumps
        environment.filters["asset_url"] = lambda value: f"/assets/{value}"
        return environment

    def order(
        self,
        *,
        days_ago: int,
        sku: str | None = None,
        handle: str | None = None,
        quantity: int = 1,
        cancelled: bool = False,
        with_lines: bool = True,
    ) -> dict:
        line: dict = {"quantity": quantity}
        if sku:
            line["sku"] = sku
        if handle:
            line["product"] = {"handle": handle}
        return {
            "created_at": NOW - timedelta(days=days_ago),
            "is_cancelled": cancelled,
            "line_items": [line] if with_lines else [],
        }

    def payload(self, orders: list | None, customer_id: int | None = 42) -> dict:
        customer = None if customer_id is None else {"id": customer_id, "orders": orders or []}
        rendered = self.environment().get_template("customer-order-limit-history").render(
            customer=customer,
        )
        body = re.search(r"<script[^>]*>(.*?)</script>", rendered, re.S)
        self.assertIsNotNone(body)
        return json.loads(body.group(1))

    def test_payload_lists_line_items_with_dates_and_quantities(self) -> None:
        payload = self.payload([
            self.order(days_ago=30, sku=HANDLE, quantity=2),
            self.order(days_ago=5, handle=LOWER, quantity=1),
        ])

        self.assertEqual(payload["customer"], "42")
        self.assertFalse(payload["truncated"])
        self.assertEqual(len(payload["lines"]), 2)
        self.assertEqual(payload["lines"][0][1], LOWER)
        self.assertEqual(payload["lines"][0][3], 2)
        self.assertEqual(payload["lines"][1][0], LOWER)
        self.assertEqual(payload["lines"][1][3], 1)
        self.assertTrue(all(isinstance(line[2], int) and line[2] > 0 for line in payload["lines"]))

    def test_payload_excludes_cancelled_orders(self) -> None:
        payload = self.payload([
            self.order(days_ago=3, sku=HANDLE, quantity=9, cancelled=True),
        ])

        self.assertEqual(payload["lines"], [])

    def test_payload_is_valid_json_when_there_is_nothing_to_report(self) -> None:
        self.assertEqual(self.payload([])["lines"], [])
        guest = self.payload(None, customer_id=None)
        self.assertEqual(guest["lines"], [])
        self.assertEqual(guest["customer"], "")

    def test_product_page_reports_the_failing_shape(self) -> None:
        # Orders visible without line items: the inline pass counts zero, which is
        # exactly the state that let customers reorder a limited product.
        rendered = self.environment().get_template("customer-order-limits").render(
            customer={
                "id": 42,
                "email": "buyer@example.com",
                "orders": [self.order(days_ago=30, sku=HANDLE, quantity=2, with_lines=False)],
            },
            cart={"items": []},
        )

        diagnostics = re.search(r"diagnostics: \{(.*?)\n    \}", rendered, re.S).group(1)
        self.assertIn("ordersSeen: 1", diagnostics)
        self.assertIn("lineItemsSeen: 0", diagnostics)
        self.assertIn("purchased: 0", rendered)
        # The client needs both of these to load and filter history itself.
        self.assertIn("windowStart:", rendered)
        self.assertIn('customerId: "42"', rendered)


if __name__ == "__main__":
    unittest.main()
