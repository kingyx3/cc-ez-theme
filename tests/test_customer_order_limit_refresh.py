from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from limit_config import configured_rows  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
THEME = ROOT / "theme"

CONFIG = (THEME / "snippets" / "customer-order-limit-config.liquid").read_text(encoding="utf-8")
ROWS = configured_rows(CONFIG)


class CustomerOrderLimitRefreshTests(unittest.TestCase):
    """A refresh timestamp renews a handle's allowance once it passes."""

    def read(self, relative: str) -> str:
        return (THEME / relative).read_text(encoding="utf-8")

    def test_every_row_carries_its_own_refresh_date(self) -> None:
        config = self.read("snippets/customer-order-limit-config.liquid")

        self.assertTrue(ROWS)
        for handle, _, refresh in ROWS:
            with self.subTest(handle=handle):
                # The date the allowance counts from is part of the row that
                # configures the limit, not a separate list to keep in step.
                self.assertIn(f"limit_handle: '{handle}'", config)
                # Every row inherits the shared date today; a row that needs a
                # different one writes it here rather than anywhere else.
                self.assertEqual(refresh, "")
        self.assertNotIn("split:", config)

    def test_every_limit_counts_from_the_configured_store_date(self) -> None:
        config = self.read("snippets/customer-order-limit-config.liquid")

        # Configured 9 Aug 2026 00:00 store time (GMT+8). A blank row falls back
        # to this, so one line moves every limit onto the same window.
        self.assertIn(
            "{% assign customer_order_limit_refresh_all = '2026-08-09 00:00:00 +0800' %}",
            config,
        )
        self.assertEqual(config.count("customer_order_limit_refresh_all"), 2)

    def test_refresh_documentation_states_the_expected_format(self) -> None:
        config = self.read("snippets/customer-order-limit-config.liquid")

        self.assertIn("'2026-09-01 00:00:00 +0800'", config)
        self.assertIn("customer_order_limit_refresh_all", config)
        self.assertIn("A timestamp in the future changes", config)
        # The point of the date: a limit is measured over a window rather than
        # over every order the customer has ever placed.
        self.assertIn("instead of over every order ever placed", config)

    def test_window_snippet_resolves_one_timestamp(self) -> None:
        window = self.read("snippets/customer-order-limit-window.liquid")

        # Default fallback, then epoch comparison, then the display label.
        self.assertIn("{% assign customer_order_limit_window = 0 %}", window)
        # Values are forced to strings and compared with '', not with `blank`,
        # and the epoch must land past 1970: a live store activated a window at
        # epoch 0 from an unconfigured slot.
        self.assertIn(
            "{% assign customer_order_limit_window_refresh = window_refresh"
            " | default: '' | append: '' | strip %}",
            window,
        )
        self.assertIn(
            "{% assign customer_order_limit_window_refresh = window_default"
            " | default: '' | append: '' | strip %}",
            window,
        )
        self.assertIn("{% if customer_order_limit_window_refresh == '' %}", window)
        self.assertIn("{% if customer_order_limit_window_refresh != '' %}", window)
        self.assertIn("| date: '%s' | plus: 0 %}", window)
        self.assertIn(
            "{% if customer_order_limit_window_epoch > 86400 "
            "and customer_order_limit_window_current >= customer_order_limit_window_epoch %}",
            window,
        )
        self.assertNotIn("!= blank", window)
        self.assertIn("| date: '%b %d, %Y' %}", window)

    def test_a_row_resolves_its_own_window(self) -> None:
        liquid = self.read("snippets/customer-order-limits.liquid")
        row = self.read("snippets/customer-order-limit-row.liquid")

        self.assertIn("{% assign customer_order_limit_now_epoch = 'now' | date: '%s' | plus: 0 %}", liquid)
        self.assertIn(
            "{% include 'customer-order-limit-window', window_refresh: limit_refresh,"
            " window_default: customer_order_limit_refresh_all,"
            " window_now: customer_order_limit_now_epoch %}",
            row,
        )
        self.assertIn(
            "{% assign customer_order_limit_row_window = customer_order_limit_window %}",
            row,
        )

    def test_order_pass_ignores_orders_placed_before_the_window(self) -> None:
        row = self.read("snippets/customer-order-limit-row.liquid")

        self.assertIn(
            "{% assign customer_order_limit_row_order_epoch = order.created_at | date: '%s' | plus: 0 %}",
            row,
        )
        # An unreadable date must keep counting, otherwise a date-format change
        # would silently clear every limit.
        self.assertIn(
            "{% assign customer_order_limit_row_order_epoch = order.processed_at | date: '%s' | plus: 0 %}",
            row,
        )
        self.assertIn(
            "{% assign customer_order_limit_row_order_epoch = customer_order_limit_now_epoch %}",
            row,
        )
        self.assertIn(
            "{% if customer_order_limit_row_order_epoch >= customer_order_limit_row_window %}",
            row,
        )
        # Cancelled orders stay excluded, and the single-pass loops are intact.
        # The flag is an integer on EasyStore, so it is compared by value: Liquid
        # treats 0 as truthy and an unless on the raw value skipped every order.
        self.assertNotIn("{% unless order.is_cancelled %}", row)
        self.assertIn(
            "{% assign customer_order_limit_row_cancelled = order.is_cancelled"
            " | default: 0 | append: '' | strip | downcase %}",
            row,
        )
        self.assertIn(
            "{% unless customer_order_limit_row_cancelled == '1'"
            " or customer_order_limit_row_cancelled == 'true' %}",
            row,
        )
        self.assertEqual(row.count("{% for order in customer_order_limit_row_orders %}"), 1)
        self.assertEqual(row.count("{% for line_item in customer_order_limit_row_lines %}"), 1)

    def test_history_matches_a_line_item_on_handle_or_sku(self) -> None:
        row = self.read("snippets/customer-order-limit-row.liquid")

        # Matching product.handle alone counted zero units on a store whose order
        # line items expose the SKU instead, so the limit never applied across
        # orders. Both identifiers now count, for history and for the cart.
        self.assertIn(
            "{% assign customer_order_limit_row_line_sku = line_item.sku"
            " | default: line_item.variant.sku | default: line_item.product.sku"
            " | default: '' | append: '' | strip | downcase %}",
            row,
        )
        self.assertIn(
            "{% assign customer_order_limit_row_cart_sku = cart_item.sku"
            " | default: cart_item.variant.sku | default: cart_item.product.sku"
            " | default: '' | append: '' | strip | downcase %}",
            row,
        )
        self.assertIn(
            "customer_order_limit_row_line_handle == customer_order_limit_row_handle"
            " or customer_order_limit_row_line_sku == customer_order_limit_row_handle",
            row,
        )
        self.assertIn(
            "customer_order_limit_row_cart_handle == customer_order_limit_row_handle"
            " or customer_order_limit_row_cart_sku == customer_order_limit_row_handle",
            row,
        )
        # A row only runs for a non-blank handle, so a line item with no handle
        # and no SKU reads as '' and can never match. The comparison is against
        # '' on string-forced values, never `blank`.
        self.assertIn("{% if customer_order_limit_row_handle != '' and", row)
        self.assertNotIn("== blank", row)
        self.assertNotIn("!= blank", row)
        # Quantities read a fallback field name too.
        self.assertIn("line_item.quantity | default: line_item.qty | default: 0 | plus: 0", row)
        self.assertIn("cart_item.quantity | default: cart_item.qty | default: 0 | plus: 0", row)

    def test_payload_reports_what_the_order_pass_could_read(self) -> None:
        liquid = self.read("snippets/customer-order-limits.liquid")

        # Without this, "the limit is not enforcing" cannot be told apart from
        # "the storefront cannot see order history" without another release.
        self.assertIn("diagnostics: {", liquid)
        self.assertIn("ordersSeen: {{ customer_order_limit_orders_seen | json }},", liquid)
        self.assertIn("lineItemsSeen: {{ customer_order_limit_lines_seen | json }},", liquid)
        self.assertIn("identifiers: {{ customer_order_limit_sample | strip | json }},", liquid)
        self.assertIn("{% if customer_order_limit_sample_count < 5 %}", liquid)

    def test_rule_payload_carries_the_refresh_state(self) -> None:
        row = self.read("snippets/customer-order-limit-row.liquid")
        rule = self.read("snippets/customer-order-limit-rule.liquid")

        self.assertIn("rule_refresh_at: customer_order_limit_window_refresh,", row)
        self.assertIn("rule_window_label: customer_order_limit_window_label,", row)
        self.assertIn("rule_window_start: customer_order_limit_row_window", row)
        self.assertIn("refreshAt: {{ customer_order_limit_rule_refresh_at | json }},", rule)
        self.assertIn("limitWindowLabel: {{ customer_order_limit_rule_window_label | json }},", rule)

    def test_storefront_copy_never_names_the_refresh_date(self) -> None:
        # The date an allowance is counted from is store configuration. It stays
        # on the rule for console verification and drives which orders count, but
        # no shopper-facing message mentions it.
        rule = self.read("snippets/customer-order-limit-rule.liquid")
        limits = self.read("assets/customer-order-limits.js")

        self.assertNotIn("customer_order_limit_rule_since", rule)
        self.assertNotIn("sinceLabel", limits)
        self.assertNotIn(" since ", limits)
        self.assertIn("per customer.", rule)
        self.assertIn("per customer.`", limits)
        self.assertEqual(limits, self.read("editor_assets/customer-order-limits.js"))

    def test_window_and_row_snippets_are_packaged_liquid_only(self) -> None:
        window = self.read("snippets/customer-order-limit-window.liquid")

        # Pure Liquid: the renewal must not depend on storefront JavaScript, and
        # nothing here may reach for EasyStore APIs.
        self.assertNotIn("<script", window)
        self.assertNotIn("EasyStore", window)
        self.assertIsNone(re.search(r"{%\s*(render|form|paginate)\b", window))
        # A row publishes its rule through the rule snippet, so it holds no
        # markup of its own either.
        row = self.read("snippets/customer-order-limit-row.liquid")
        self.assertNotIn("<script", row)
        self.assertIsNone(re.search(r"{%\s*(render|form|paginate)\b", row))


if __name__ == "__main__":
    unittest.main()
