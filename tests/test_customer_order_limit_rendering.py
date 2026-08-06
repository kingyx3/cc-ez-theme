"""Renders the limit Liquid snippets and checks the numbers they produce.

The rest of the suite reads the snippets as text. This module executes them with
fake order history, which is the only way to catch the mistakes that have
actually shipped: purchases that never counted, and allowances that renewed at
the wrong time.

python-liquid is not EasyStore's renderer, so a pass here proves the logic, not
the platform. Verify field names on a real unpublished theme as well.
"""
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


SNIPPETS = Path(__file__).resolve().parents[1] / "theme" / "snippets"
SLOT_COUNT = len(re.findall(
    r"customer_order_limit_handle_(\d+) =",
    (SNIPPETS / "customer-order-limit-config.liquid").read_text(encoding="utf-8"),
))
NOW = datetime.now(timezone.utc)
STAMP = "%Y-%m-%d %H:%M:%S +0000"
HANDLE = "MTG-HOB-SCN-EN-SET2"
LOWER = HANDLE.lower()


def config_liquid(handle: str, maximum: int, refresh: str, refresh_all: str) -> str:
    lines = [
        f"{{% assign customer_order_limit_refresh_all = '{refresh_all}' %}}",
        f"{{% assign customer_order_limit_handle_1 = '{handle}' %}}",
        f"{{% assign customer_order_limit_maximum_1 = {maximum} %}}",
        f"{{% assign customer_order_limit_refresh_1 = '{refresh}' %}}",
    ]
    for slot in range(2, SLOT_COUNT + 1):
        lines += [
            f"{{% assign customer_order_limit_handle_{slot} = '' %}}",
            f"{{% assign customer_order_limit_maximum_{slot} = 0 %}}",
            f"{{% assign customer_order_limit_refresh_{slot} = '' %}}",
        ]
    return "\n".join(lines) + "\n"


@unittest.skipIf(Environment is None, "python-liquid is not installed")
class CustomerOrderLimitRenderingTests(unittest.TestCase):
    def render(
        self,
        *,
        maximum: int = 1,
        refresh: str = "",
        refresh_all: str = "",
        orders: list | None = None,
        cart_items: list | None = None,
        authenticated: bool = True,
    ) -> str:
        loader = DictLoader({
            "customer-order-limit-config": config_liquid(HANDLE, maximum, refresh, refresh_all),
            "customer-order-limit-window": (SNIPPETS / "customer-order-limit-window.liquid").read_text(encoding="utf-8"),
            "customer-order-limit-rule": (SNIPPETS / "customer-order-limit-rule.liquid").read_text(encoding="utf-8"),
            "customer-order-limits": (SNIPPETS / "customer-order-limits.liquid").read_text(encoding="utf-8"),
        })
        environment = Environment(loader=loader)
        environment.filters["json"] = json.dumps
        environment.filters["asset_url"] = lambda value: f"/assets/{value}"
        customer = (
            {"id": 42, "email": "buyer@example.com", "orders": orders or []}
            if authenticated
            else None
        )
        return environment.get_template("customer-order-limits").render(
            customer=customer,
            cart={"items": cart_items or []},
        )

    def rule(self, output: str, handle: str = LOWER) -> dict:
        rules = self.rules(output)
        self.assertIn(handle, rules)
        return rules[handle]

    def rules(self, output: str) -> dict:
        found = {}
        pattern = r"window\.customerOrderLimitsV2\.rules\[(\".*?\")\] = (\{.*?\n    \});"
        for match in re.finditer(pattern, output, re.S):
            payload = {}
            for field in re.finditer(r"(\w+): (\".*?\"|true|false|-?\d+)", match.group(2)):
                payload[field.group(1)] = json.loads(field.group(2))
            found[json.loads(match.group(1))] = payload
        return found

    def diagnostics(self, output: str) -> dict:
        block = re.search(r"diagnostics: \{(.*?)\n    \}", output, re.S)
        self.assertIsNotNone(block)
        parsed = {}
        for field in re.finditer(r"(\w+): (\".*?\"|-?\d+)", block.group(1)):
            parsed[field.group(1)] = json.loads(field.group(2))
        return parsed

    def order(
        self,
        *,
        days_ago: int,
        handle: str | None = None,
        sku: str | None = None,
        quantity: int = 1,
        cancelled: bool = False,
    ) -> dict:
        line: dict = {"quantity": quantity}
        if handle is not None:
            line["product"] = {"handle": handle}
        if sku is not None:
            line["sku"] = sku
        return {
            "created_at": NOW - timedelta(days=days_ago),
            "is_cancelled": cancelled,
            "line_items": [line],
        }

    def passed_refresh(self) -> str:
        return (NOW - timedelta(days=7)).strftime(STAMP)

    def future_refresh(self) -> str:
        return (NOW + timedelta(days=30)).strftime(STAMP)

    # --- purchase history ---------------------------------------------------

    def test_past_orders_consume_the_allowance(self) -> None:
        rule = self.rule(self.render(orders=[self.order(days_ago=30, handle=LOWER)]))

        self.assertEqual(rule["purchased"], 1)
        self.assertEqual(rule["allowedCartQuantity"], 0)
        self.assertEqual(rule["remaining"], 0)

    def test_a_line_item_with_only_a_sku_still_counts(self) -> None:
        # The reported failure: customers reordered the same product because the
        # history pass matched product.handle only.
        rule = self.rule(self.render(orders=[self.order(days_ago=30, sku=HANDLE)]))

        self.assertEqual(rule["purchased"], 1)
        self.assertEqual(rule["remaining"], 0)

    def test_quantities_accumulate_across_orders(self) -> None:
        rule = self.rule(self.render(
            maximum=3,
            orders=[
                self.order(days_ago=30, handle=LOWER),
                self.order(days_ago=3, sku=HANDLE, quantity=2),
            ],
        ))

        self.assertEqual(rule["purchased"], 3)
        self.assertEqual(rule["remaining"], 0)

    def test_cancelled_orders_never_count(self) -> None:
        rule = self.rule(self.render(
            orders=[self.order(days_ago=5, handle=LOWER, cancelled=True)],
        ))

        self.assertEqual(rule["purchased"], 0)
        self.assertEqual(rule["remaining"], 1)

    def test_other_products_are_untouched(self) -> None:
        output = self.render(
            orders=[self.order(days_ago=2, handle="some-other-product", sku="OTHER-SKU")],
            cart_items=[{"product": {"handle": "some-other-product"}, "quantity": 5}],
        )
        rule = self.rule(output)

        self.assertEqual(rule["purchased"], 0)
        self.assertEqual(rule["cartQuantity"], 0)

    def test_line_item_without_identifiers_matches_nothing(self) -> None:
        output = self.render(orders=[self.order(days_ago=2, quantity=4)])

        self.assertEqual(self.rule(output)["purchased"], 0)
        # Blank slots stay silent, so an unconfigured slot cannot absorb it.
        self.assertEqual(len(self.rules(output)), 1)

    def test_a_guest_render_reads_no_history(self) -> None:
        output = self.render(
            orders=[self.order(days_ago=2, handle=LOWER)],
            authenticated=False,
        )
        rule = self.rule(output)

        self.assertIn("customerAuthenticated: false", output)
        self.assertTrue(rule["loginRequired"])
        self.assertEqual(rule["purchased"], 0)

    # --- cart ---------------------------------------------------------------

    def test_cart_lines_count_by_handle_and_by_sku(self) -> None:
        rule = self.rule(self.render(
            maximum=2,
            cart_items=[
                {"product": {"handle": LOWER}, "quantity": 1},
                {"sku": HANDLE, "quantity": 1},
            ],
        ))

        self.assertEqual(rule["cartQuantity"], 2)
        self.assertEqual(rule["remaining"], 0)
        self.assertFalse(rule["cartExceeded"])

    def test_cart_beyond_the_allowance_is_flagged(self) -> None:
        rule = self.rule(self.render(
            orders=[],
            cart_items=[{"sku": HANDLE, "quantity": 2}],
        ))

        self.assertEqual(rule["cartQuantity"], 2)
        self.assertTrue(rule["cartExceeded"])

    # --- refresh windows ----------------------------------------------------

    def test_a_passed_refresh_renews_the_allowance(self) -> None:
        rule = self.rule(self.render(
            refresh=self.passed_refresh(),
            orders=[self.order(days_ago=30, handle=LOWER)],
        ))

        self.assertEqual(rule["purchased"], 0)
        self.assertEqual(rule["remaining"], 1)
        self.assertTrue(rule["limitWindowLabel"])
        self.assertIn("since", rule["message"])

    def test_orders_after_the_refresh_still_count(self) -> None:
        rule = self.rule(self.render(
            refresh=self.passed_refresh(),
            orders=[
                self.order(days_ago=30, handle=LOWER),
                self.order(days_ago=2, handle=LOWER),
            ],
        ))

        self.assertEqual(rule["purchased"], 1)
        self.assertEqual(rule["remaining"], 0)

    def test_a_future_refresh_changes_nothing_yet(self) -> None:
        future = self.future_refresh()
        rule = self.rule(self.render(
            refresh=future,
            orders=[self.order(days_ago=30, handle=LOWER)],
        ))

        self.assertEqual(rule["purchased"], 1)
        self.assertEqual(rule["limitWindowLabel"], "")
        # The configured value is still published so it can be verified.
        self.assertEqual(rule["refreshAt"], future)

    def test_the_shared_default_renews_slots_without_their_own(self) -> None:
        rule = self.rule(self.render(
            refresh_all=self.passed_refresh(),
            orders=[self.order(days_ago=30, handle=LOWER)],
        ))

        self.assertEqual(rule["purchased"], 0)

    def test_a_slot_refresh_overrides_the_shared_default(self) -> None:
        rule = self.rule(self.render(
            refresh=self.future_refresh(),
            refresh_all=self.passed_refresh(),
            orders=[self.order(days_ago=30, handle=LOWER)],
        ))

        self.assertEqual(rule["purchased"], 1)

    def test_an_unreadable_refresh_leaves_the_limit_alone(self) -> None:
        rule = self.rule(self.render(
            refresh="whenever",
            orders=[self.order(days_ago=30, handle=LOWER)],
        ))

        self.assertEqual(rule["purchased"], 1)
        self.assertEqual(rule["limitWindowLabel"], "")

    # --- diagnostics --------------------------------------------------------

    def test_diagnostics_report_what_the_pass_could_read(self) -> None:
        diagnostics = self.diagnostics(self.render(
            orders=[self.order(days_ago=30, sku=HANDLE, quantity=2)],
        ))

        self.assertEqual(diagnostics["ordersSeen"], 1)
        self.assertEqual(diagnostics["lineItemsSeen"], 1)
        self.assertEqual(diagnostics["identifiers"], f"-no-handle-/{LOWER}x2")

    def test_diagnostics_show_an_empty_history_as_zero(self) -> None:
        diagnostics = self.diagnostics(self.render(orders=[]))

        self.assertEqual(diagnostics["ordersSeen"], 0)
        self.assertEqual(diagnostics["lineItemsSeen"], 0)
        self.assertEqual(diagnostics["identifiers"], "")


if __name__ == "__main__":
    unittest.main()
