from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "theme"


class CustomerOrderHistoryDetailFallbackTests(unittest.TestCase):
    def read(self, path: str) -> str:
        return (ROOT / path).read_text(encoding="utf-8")

    def test_runtime_and_editor_assets_match(self) -> None:
        self.assertEqual(
            self.read("assets/customer-order-history-fallback.js"),
            self.read("editor_assets/customer-order-history-fallback.js"),
        )

    def test_detail_fallback_loads_before_the_purchase_limit_validator(self) -> None:
        snippet = self.read("snippets/customer-order-limits.liquid")
        fallback = "customer-order-history-fallback.js"
        validator = "customer-order-limits.js"
        self.assertIn(fallback, snippet)
        self.assertLess(snippet.index(fallback), snippet.index(validator))

    def test_only_empty_account_history_payloads_are_hydrated(self) -> None:
        fallback = self.read("assets/customer-order-history-fallback.js")
        self.assertIn("url.pathname === HISTORY_PATH", fallback)
        self.assertIn("existingLines.length", fallback)
        self.assertIn("diagnostics.ordersSeen", fallback)
        self.assertIn("article.flex-table-tr", fallback)
        self.assertIn("/account/orders/", fallback)

    def test_order_details_supply_handle_quantity_and_stable_identity(self) -> None:
        fallback = self.read("assets/customer-order-history-fallback.js")
        self.assertIn(".product-qty-badge", fallback)
        self.assertIn("a[href*=\"/products/\"]", fallback)
        self.assertIn("detail:${token}:${index}", fallback)
        self.assertIn(".label-tag-alert", fallback)


if __name__ == "__main__":
    unittest.main()
