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
import os
import re
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from limit_config import configured_rows, row_liquid  # noqa: E402

try:  # pragma: no cover - exercised by the absence of the dependency
    from liquid import DictLoader, Environment
except ImportError:  # pragma: no cover
    DictLoader = None
    Environment = None

# Skipping is for a developer who has not installed requirements-dev yet. In CI
# the dependency is pinned, so a missing engine is a broken build rather than a
# reason to quietly drop every check in this module.
REQUIRE_ENGINE = bool(os.environ.get("CI"))


SNIPPETS = Path(__file__).resolve().parents[1] / "theme" / "snippets"
NOW = datetime.now(timezone.utc)
STAMP = "%Y-%m-%d %H:%M:%S +0000"
HANDLE = "MTG-HOB-SCN-EN-SET2"
LOWER = HANDLE.lower()
# A product whose SKU differs from its handle, so the two are proved to be
# published separately. It names no catalog product: what these checks need is
# a value that is not the handle, not a SKU the store has to keep selling.
FIXTURE_SKU = "E2E-FIXTURE-SKU-EN"


def config_liquid(rows: str, refresh_all: str) -> str:
    return (
        f"{{% assign customer_order_limit_refresh_all = '{refresh_all}' %}}\n"
        f"{rows}\n"
    )


@unittest.skipIf(
    Environment is None and not REQUIRE_ENGINE,
    "python-liquid is not installed; run pip install -r requirements-dev.txt",
)
class CustomerOrderLimitRenderingTests(unittest.TestCase):
    def setUp(self) -> None:
        if Environment is None:
            self.fail(
                "python-liquid is required in CI: these checks are the only ones "
                "that execute the limit Liquid, so skipping them hides the logic "
                "that has broken in production before."
            )

    def render(
        self,
        *,
        maximum: int = 1,
        refresh: str = "",
        refresh_all: str = "",
        rows: str | None = None,
        orders: list | None = None,
        cart_items: list | None = None,
        authenticated: bool = True,
        product: dict | None = None,
    ) -> str:
        if rows is None:
            rows = row_liquid(HANDLE, maximum, refresh)
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
        files["customer-order-limit-config"] = config_liquid(rows, refresh_all)
        loader = DictLoader(files)
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
            product=product,
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
        cancelled: object = 0,
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

    def test_an_order_counts_whatever_shape_the_cancelled_flag_takes(self) -> None:
        # EasyStore sends is_cancelled as an integer — this theme's own order list
        # compares it with `== 1` — and Liquid treats 0 as truthy, so an unless on
        # the raw value skipped every order and counted zero units for everyone.
        for flag in (0, "0", False, None, "", "false"):
            with self.subTest(flag=flag):
                order = self.order(days_ago=30, sku=HANDLE)
                if flag is None:
                    del order["is_cancelled"]
                else:
                    order["is_cancelled"] = flag
                rule = self.rule(self.render(orders=[order]))
                self.assertEqual(rule["purchased"], 1)
                self.assertEqual(rule["remaining"], 0)

        for flag in (1, "1", True, "true"):
            with self.subTest(flag=flag):
                order = self.order(days_ago=30, sku=HANDLE)
                order["is_cancelled"] = flag
                self.assertEqual(self.rule(self.render(orders=[order]))["purchased"], 0)

    def test_the_page_publishes_its_product_identifiers(self) -> None:
        # A line item is only guaranteed to expose the variant id, so the product's
        # own ids are published for the storefront to match history against.
        rendered = self.render(product={
            "handle": LOWER,
            "sku": FIXTURE_SKU,
            "id": 700,
            "variants": [{"id": 9911}, {"id": 9912}],
        })

        self.assertIn(f'handle: "{LOWER}"', rendered)
        self.assertIn(f'sku: "{FIXTURE_SKU.lower()}"', rendered)
        self.assertIn('productId: "700"', rendered)
        self.assertIn('variantIds: ["9911","9912"]', rendered)

    def test_a_page_without_a_product_publishes_empty_identifiers(self) -> None:
        # The snippet runs on the cart and on listings too.
        rendered = self.render()

        self.assertIn('handle: ""', rendered)
        self.assertIn('productId: ""', rendered)
        self.assertIn("variantIds: []", rendered)

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
            orders=[self.order(days_ago=5, handle=LOWER, cancelled=1)],
        ))

        self.assertEqual(rule["purchased"], 0)
        self.assertEqual(rule["remaining"], 1)

    def test_a_cancellation_counts_under_every_field_easystore_exposes(self) -> None:
        # The reported failure: cancelled orders still consumed the allowance.
        # `is_cancelled` was the only field read, and it is only the spelling the
        # account order list uses — the order detail page reads `order.cancelled`,
        # so an order shape carrying that one looked live and was counted. Each
        # field is proved on its own, with `is_cancelled` absent, because the
        # order objects a product page receives are not the ones that carry it.
        cancellations: tuple[dict, ...] = (
            {"cancelled": True},
            {"cancelled": 1},
            {"cancelled": "1"},
            {"cancelled": "true"},
            {"cancelled_at": (NOW - timedelta(days=1)).strftime(STAMP)},
            {"status": "cancelled"},
            {"status": "canceled"},
            {"order_status": "cancelled"},
            {"financial_status_label": "Cancelled"},
            {"financial_status": "cancelled"},
            {"fulfillment_status_label": "Cancelled"},
            {"fulfillment_status": "cancelled"},
        )
        for fields in cancellations:
            with self.subTest(fields=fields):
                order = self.order(days_ago=5, handle=LOWER, sku=HANDLE)
                del order["is_cancelled"]
                order.update(fields)
                rule = self.rule(self.render(orders=[order]))
                self.assertEqual(rule["purchased"], 0)
                self.assertEqual(rule["remaining"], 1)

    def test_a_live_order_still_counts_under_every_other_status(self) -> None:
        # The other half of the same change: broadening the fields read must not
        # start reading a live order as cancelled. A refund is deliberately not a
        # cancellation — the order was placed, and whether it frees an allowance
        # is the merchant's call — and the falsy shapes say nothing at all.
        live: tuple[dict, ...] = (
            {"cancelled": False},
            {"cancelled": 0},
            {"cancelled": ""},
            {"cancelled_at": ""},
            {"cancelled_at": None},
            {"status": "to_pay"},
            {"status": "to_receive"},
            {"status": "completed"},
            {"financial_status_label": "Paid"},
            {"financial_status_label": "Refunded"},
            {"fulfillment_status_label": "Fulfilled"},
            {"fulfillment_status_label": "Returned"},
        )
        for fields in live:
            with self.subTest(fields=fields):
                order = self.order(days_ago=5, handle=LOWER, sku=HANDLE)
                del order["is_cancelled"]
                order.update(fields)
                self.assertEqual(self.rule(self.render(orders=[order]))["purchased"], 1)

    def test_an_order_exposing_no_cancellation_field_still_counts(self) -> None:
        # An unreadable order is never a free allowance: with no field to read,
        # the order counts and the limit stays enforced.
        order = self.order(days_ago=5, handle=LOWER)
        del order["is_cancelled"]

        self.assertEqual(self.rule(self.render(orders=[order]))["purchased"], 1)

    def test_the_cancellation_snippet_reads_the_order_in_scope_too(self) -> None:
        # `include` shares the caller's scope on EasyStore, and whether it also
        # binds an object passed as a parameter is the platform's business. The
        # snippet is therefore rendered here the way an engine that ignored the
        # parameter would render it — no input, only the loop variable in scope —
        # because that shape must still recognise a cancelled order rather than
        # silently counting every one of them.
        files = {
            "customer-order-limit-cancelled": (
                SNIPPETS / "customer-order-limit-cancelled.liquid"
            ).read_text(encoding="utf-8"),
            "caller": (
                "{% for order in orders %}"
                "{% include 'customer-order-limit-cancelled' %}"
                "[{{ customer_order_limit_cancelled }}]"
                "{% endfor %}"
            ),
        }
        environment = Environment(loader=DictLoader(files))
        environment.filters["json"] = json.dumps

        rendered = environment.get_template("caller").render(orders=[
            {"is_cancelled": 0},
            {"is_cancelled": 1},
            {"cancelled": True},
            {"status": "cancelled"},
            {},
        ])
        decisions = re.findall(r"\[(true|false)\]", rendered)

        self.assertEqual(decisions, ["false", "true", "true", "true", "false"])

    def test_diagnostics_report_what_the_cancellation_pass_decided(self) -> None:
        # A cancelled order that still counts is a field name this theme is not
        # reading, and the raw values are the only way to tell which one from a
        # live store rather than from a guess.
        output = self.render(orders=[
            self.order(days_ago=5, handle=LOWER),
            self.order(days_ago=4, handle=LOWER, cancelled=1),
            dict(self.order(days_ago=3, handle=LOWER), status="cancelled"),
        ])
        diagnostics = self.diagnostics(output)

        self.assertEqual(diagnostics["ordersSeen"], 1)
        self.assertEqual(diagnostics["cancelledOrdersSeen"], 2)
        self.assertEqual(diagnostics["lineItemsSeen"], 1)
        self.assertEqual(self.rule(output)["purchased"], 1)
        self.assertIn("counted is_cancelled=0", diagnostics["orderStatuses"])
        self.assertIn("skipped is_cancelled=1", diagnostics["orderStatuses"])
        self.assertIn("status=cancelled", diagnostics["orderStatuses"])

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
        # The window drives which orders count; it is never quoted to a shopper.
        self.assertNotIn("since", rule["message"])
        self.assertNotIn(rule["limitWindowLabel"], rule["message"])

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

    def test_an_unconfigured_slot_never_activates_a_window(self) -> None:
        # A live store reported copy counting "since Jan 01, 1970": an empty
        # refresh reached the epoch comparison and won it.
        rule = self.rule(self.render(orders=[self.order(days_ago=30, handle=LOWER)]))

        self.assertEqual(rule["limitWindowLabel"], "")
        self.assertEqual(rule["windowStart"], 0)
        self.assertNotIn("since", rule["message"])
        self.assertEqual(rule["purchased"], 1)

    def test_a_refresh_at_the_epoch_start_is_treated_as_unset(self) -> None:
        rule = self.rule(self.render(
            refresh="1970-01-01 00:00:00 +0000",
            orders=[self.order(days_ago=30, handle=LOWER)],
        ))

        self.assertEqual(rule["limitWindowLabel"], "")
        self.assertEqual(rule["purchased"], 1)

    def test_an_unreadable_refresh_leaves_the_limit_alone(self) -> None:
        rule = self.rule(self.render(
            refresh="whenever",
            orders=[self.order(days_ago=30, handle=LOWER)],
        ))

        self.assertEqual(rule["purchased"], 1)
        self.assertEqual(rule["limitWindowLabel"], "")

    # --- one row per limit --------------------------------------------------

    def test_one_row_adds_a_limit(self) -> None:
        # The whole point of the row: a product is added by writing this line and
        # nothing else.
        rules = self.rules(self.render(
            rows=row_liquid("MTG-HOB-SCN-EN-SET2", 2) + "\n" + row_liquid("CC-BDL-UNEXPECTED-EN", 1),
            orders=[self.order(days_ago=10, sku="CC-BDL-UNEXPECTED-EN")],
            cart_items=[{"product": {"handle": LOWER}, "quantity": 1}],
        ))

        self.assertEqual(sorted(rules), ["cc-bdl-unexpected-en", "mtg-hob-scn-en-set2"])
        self.assertEqual(rules["cc-bdl-unexpected-en"]["purchased"], 1)
        self.assertEqual(rules["cc-bdl-unexpected-en"]["remaining"], 0)
        self.assertEqual(rules["mtg-hob-scn-en-set2"]["cartQuantity"], 1)
        self.assertEqual(rules["mtg-hob-scn-en-set2"]["remaining"], 1)

    def test_each_row_keeps_its_own_refresh_date(self) -> None:
        # `include` shares the caller's scope on EasyStore, so a row's timestamp
        # must not leak into the next row and renew a limit that never asked for
        # it — including a row that omits limit_refresh entirely.
        rows = "\n".join((
            row_liquid("RENEWED-HANDLE", 2, self.passed_refresh()),
            row_liquid("KEPT-HANDLE", 2),
            "{% include 'customer-order-limit-row', limit_handle: 'OMITTED-HANDLE',"
            " limit_maximum: 2 %}",
        ))
        rules = self.rules(self.render(
            rows=rows,
            orders=[
                self.order(days_ago=30, handle="renewed-handle"),
                self.order(days_ago=30, handle="kept-handle"),
                self.order(days_ago=30, handle="omitted-handle"),
            ],
        ))

        self.assertEqual(rules["renewed-handle"]["purchased"], 0)
        self.assertTrue(rules["renewed-handle"]["limitWindowLabel"])
        for handle in ("kept-handle", "omitted-handle"):
            with self.subTest(handle=handle):
                self.assertEqual(rules[handle]["purchased"], 1)
                self.assertEqual(rules[handle]["refreshAt"], "")
                self.assertEqual(rules[handle]["windowStart"], 0)

    def test_a_row_without_a_handle_or_a_maximum_publishes_nothing(self) -> None:
        rows = "\n".join((
            row_liquid("", 5),
            row_liquid("ZERO-HANDLE", 0),
            row_liquid(HANDLE, 1),
        ))
        rules = self.rules(self.render(rows=rows, cart_items=[{"sku": "", "quantity": 2}]))

        self.assertEqual(list(rules), [LOWER])
        self.assertEqual(rules[LOWER]["cartQuantity"], 0)

    def test_a_row_counts_only_its_own_product(self) -> None:
        rows = "\n".join((row_liquid(HANDLE, 3), row_liquid("OTHER-HANDLE", 3)))
        rules = self.rules(self.render(
            rows=rows,
            orders=[self.order(days_ago=6, handle=LOWER, quantity=2)],
            cart_items=[{"sku": "OTHER-HANDLE", "quantity": 1}],
        ))

        self.assertEqual((rules[LOWER]["purchased"], rules[LOWER]["cartQuantity"]), (2, 0))
        self.assertEqual((rules["other-handle"]["purchased"], rules["other-handle"]["cartQuantity"]), (0, 1))

    # --- the shipped configuration ------------------------------------------

    def test_the_shipped_configuration_counts_from_its_store_date(self) -> None:
        # The real config, rendered: every limit counts from 9 Aug 2026 store
        # time, so an order placed before it no longer consumes an allowance.
        files = {
            name: (SNIPPETS / f"{name}.liquid").read_text(encoding="utf-8")
            for name in (
                "customer-order-limit-window",
                "customer-order-limit-cancelled",
                "customer-order-limit-rule",
                "customer-order-limit-row",
                "customer-order-limit-config",
                "customer-order-limits",
            )
        }
        environment = Environment(loader=DictLoader(files))
        environment.filters["json"] = json.dumps
        environment.filters["asset_url"] = lambda value: f"/assets/{value}"
        before = datetime(2026, 8, 1, tzinfo=timezone.utc)
        after = datetime(2026, 8, 10, 12, tzinfo=timezone.utc)
        orders = [
            {"created_at": before, "is_cancelled": 0,
             "line_items": [{"product": {"handle": LOWER}, "quantity": 2}]},
            {"created_at": after, "is_cancelled": 0,
             "line_items": [{"sku": "MTG-HOB-BDL-EN", "quantity": 1}]},
        ]
        rendered = environment.get_template("customer-order-limits").render(
            customer={"id": 42, "email": "buyer@example.com", "orders": orders},
            cart={"items": []},
            product=None,
        )
        rules = self.rules(rendered)

        # Every configured row publishes exactly one rule, whatever the store
        # currently sells. The handles and maximums themselves are pinned by
        # test_customer_order_limits; counting them again here only broke a
        # rendering check every time a product was added.
        self.assertEqual(
            sorted(rules), sorted(handle.lower() for handle, _, _ in configured_rows())
        )
        for handle, rule in rules.items():
            with self.subTest(handle=handle):
                self.assertEqual(rule["refreshAt"], "2026-08-09 00:00:00 +0800")
                self.assertEqual(rule["limitWindowLabel"], "Aug 09, 2026")
                self.assertGreater(rule["windowStart"], 0)
                # Configuration, not copy: no message names the date.
                self.assertNotIn("Aug 09", rule["message"])
                self.assertNotIn("since", rule["message"])
        # Orders on either side of the date, on limits configured at 2 and 6.
        self.assertEqual(rules[LOWER]["purchased"], 0)
        self.assertEqual(rules[LOWER]["remaining"], 2)
        self.assertEqual(rules["mtg-hob-bdl-en"]["purchased"], 1)
        self.assertEqual(rules["mtg-hob-bdl-en"]["remaining"], 5)

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
