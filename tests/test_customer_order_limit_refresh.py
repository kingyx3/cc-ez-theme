from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
THEME = ROOT / "theme"

SLOTS = range(1, 11)


class CustomerOrderLimitRefreshTests(unittest.TestCase):
    """A refresh timestamp renews a handle's allowance once it passes."""

    def read(self, relative: str) -> str:
        return (THEME / relative).read_text(encoding="utf-8")

    def test_every_slot_has_a_refresh_field_and_a_shared_default(self) -> None:
        config = self.read("snippets/customer-order-limit-config.liquid")

        self.assertIn("{% assign customer_order_limit_refresh_all = '' %}", config)
        for slot in SLOTS:
            with self.subTest(slot=slot):
                self.assertIn(
                    "{% assign customer_order_limit_refresh_"
                    f"{slot} = '' %}}",
                    config,
                )
        # Shipping with every refresh blank keeps today's behaviour: all past
        # orders keep counting until a timestamp is configured.
        self.assertEqual(config.count("{% assign customer_order_limit_refresh_"), 11)
        self.assertNotIn("split:", config)

    def test_refresh_documentation_states_the_expected_format(self) -> None:
        config = self.read("snippets/customer-order-limit-config.liquid")

        self.assertIn("'2026-09-01 00:00:00 +0800'", config)
        self.assertIn("customer_order_limit_refresh_all", config)
        self.assertIn("A timestamp in the future changes nothing until it arrives.", config)

    def test_window_snippet_resolves_one_timestamp(self) -> None:
        window = self.read("snippets/customer-order-limit-window.liquid")

        # Default fallback, then epoch comparison, then the display label.
        self.assertIn("{% assign customer_order_limit_window = 0 %}", window)
        self.assertIn(
            "{% assign customer_order_limit_window_refresh = window_refresh | default: '' | strip %}",
            window,
        )
        self.assertIn(
            "{% assign customer_order_limit_window_refresh = window_default | default: '' | strip %}",
            window,
        )
        self.assertIn("| date: '%s' | plus: 0 %}", window)
        self.assertIn(
            "{% if customer_order_limit_window_epoch > 0 "
            "and customer_order_limit_window_current >= customer_order_limit_window_epoch %}",
            window,
        )
        self.assertIn("| date: '%b %d, %Y' %}", window)

    def test_every_slot_resolves_its_own_window(self) -> None:
        liquid = self.read("snippets/customer-order-limits.liquid")

        self.assertIn("{% assign customer_order_limit_now_epoch = 'now' | date: '%s' | plus: 0 %}", liquid)
        self.assertEqual(liquid.count("{% include 'customer-order-limit-window'"), 10)
        self.assertEqual(
            liquid.count("window_default: customer_order_limit_refresh_all"),
            10,
        )
        for slot in SLOTS:
            with self.subTest(slot=slot):
                self.assertIn(
                    f"window_refresh: customer_order_limit_refresh_{slot},",
                    liquid,
                )
                self.assertIn(
                    "{% assign customer_order_limit_window_"
                    f"{slot} = customer_order_limit_window %}}",
                    liquid,
                )

    def test_order_pass_ignores_orders_placed_before_the_window(self) -> None:
        liquid = self.read("snippets/customer-order-limits.liquid")

        self.assertIn(
            "{% assign customer_order_limit_order_epoch = order.created_at | date: '%s' | plus: 0 %}",
            liquid,
        )
        # An unreadable date must keep counting, otherwise a date-format change
        # would silently clear every limit.
        self.assertIn(
            "{% assign customer_order_limit_order_epoch = order.processed_at | date: '%s' | plus: 0 %}",
            liquid,
        )
        self.assertIn(
            "{% assign customer_order_limit_order_epoch = customer_order_limit_now_epoch %}",
            liquid,
        )
        for slot in SLOTS:
            with self.subTest(slot=slot):
                self.assertIn(
                    "{% if customer_order_limit_line_match "
                    f"and customer_order_limit_order_epoch >= customer_order_limit_window_{slot} %}}",
                    liquid,
                )
        # Cancelled orders stay excluded, and the single-pass loops are intact.
        self.assertIn("{% unless order.is_cancelled %}", liquid)
        self.assertEqual(liquid.count("{% for order in customer_order_limit_orders %}"), 1)
        self.assertEqual(liquid.count("{% for line_item in customer_order_limit_lines %}"), 1)

    def test_history_matches_a_line_item_on_handle_or_sku(self) -> None:
        liquid = self.read("snippets/customer-order-limits.liquid")

        # Matching product.handle alone counted zero units on a store whose order
        # line items expose the SKU instead, so the limit never applied across
        # orders. Both identifiers now count, for history and for the cart.
        self.assertIn(
            "{% assign customer_order_limit_line_sku = line_item.sku"
            " | default: line_item.variant.sku | default: line_item.product.sku"
            " | default: '' | strip | downcase %}",
            liquid,
        )
        self.assertIn(
            "{% assign customer_order_limit_cart_sku = cart_item.sku"
            " | default: cart_item.variant.sku | default: cart_item.product.sku"
            " | default: '' | strip | downcase %}",
            liquid,
        )
        for slot in SLOTS:
            with self.subTest(slot=slot):
                self.assertIn(
                    f"customer_order_limit_line_handle == customer_order_limit_handle_{slot}_normalized"
                    f" or customer_order_limit_line_sku == customer_order_limit_handle_{slot}_normalized",
                    liquid,
                )
                self.assertIn(
                    f"customer_order_limit_cart_handle == customer_order_limit_handle_{slot}_normalized"
                    f" or customer_order_limit_cart_sku == customer_order_limit_handle_{slot}_normalized",
                    liquid,
                )
        # A blank identifier must never match an unconfigured slot.
        self.assertIn("{% assign customer_order_limit_line_handle = '-no-handle-' %}", liquid)
        self.assertIn("{% assign customer_order_limit_line_sku = '-no-sku-' %}", liquid)
        self.assertIn("{% assign customer_order_limit_cart_handle = '-no-handle-' %}", liquid)
        self.assertIn("{% assign customer_order_limit_cart_sku = '-no-sku-' %}", liquid)
        # Quantities read a fallback field name too.
        self.assertIn("line_item.quantity | default: line_item.qty | default: 0 | plus: 0", liquid)
        self.assertIn("cart_item.quantity | default: cart_item.qty | default: 0 | plus: 0", liquid)

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
        liquid = self.read("snippets/customer-order-limits.liquid")
        rule = self.read("snippets/customer-order-limit-rule.liquid")

        self.assertEqual(liquid.count("rule_refresh_at: customer_order_limit_refresh_value_"), 10)
        self.assertEqual(liquid.count("rule_window_label: customer_order_limit_window_label_"), 10)
        self.assertIn("refreshAt: {{ customer_order_limit_rule_refresh_at | json }},", rule)
        self.assertIn("limitWindowLabel: {{ customer_order_limit_rule_window_label | json }},", rule)
        self.assertIn("across orders{{ customer_order_limit_rule_since }}", rule)

    def test_storefront_copy_names_the_date_the_limit_counts_from(self) -> None:
        limits = self.read("assets/customer-order-limits.js")

        self.assertIn("const sinceLabel = (rule) => {", limits)
        self.assertIn("rule.limitWindowLabel", limits)
        self.assertIn("return label ? ` since ${label}` : '';", limits)
        # Both the addition copy and the cart copy name the window.
        self.assertEqual(limits.count("${sinceLabel(rule)}"), 4)
        self.assertEqual(limits, self.read("editor_assets/customer-order-limits.js"))

    def test_window_snippet_is_packaged_liquid_only(self) -> None:
        window = self.read("snippets/customer-order-limit-window.liquid")

        # Pure Liquid: the renewal must not depend on storefront JavaScript, and
        # nothing here may reach for EasyStore APIs.
        self.assertNotIn("<script", window)
        self.assertNotIn("EasyStore", window)
        self.assertIsNone(re.search(r"{%\s*(render|form|paginate)\b", window))


if __name__ == "__main__":
    unittest.main()
