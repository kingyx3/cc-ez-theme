from __future__ import annotations

import os
import unittest
from pathlib import Path

try:  # pragma: no cover - exercised by the absence of the dependency
    from liquid import DictLoader, Environment
except ImportError:  # pragma: no cover
    DictLoader = None
    Environment = None


ROOT = Path(__file__).resolve().parents[1]
SNIPPET = ROOT / "theme" / "snippets" / "customer-order-limit-cancelled.liquid"
REQUIRE_ENGINE = bool(os.environ.get("CI"))


@unittest.skipIf(
    Environment is None and not REQUIRE_ENGINE,
    "python-liquid is not installed; run pip install -r requirements-dev.txt",
)
class CancellationPrecedenceTests(unittest.TestCase):
    """Native account cancellation state wins over ambiguous fallback labels."""

    def setUp(self) -> None:
        if Environment is None:
            self.fail("python-liquid is required in CI")
        files = {
            "customer-order-limit-cancelled": SNIPPET.read_text(encoding="utf-8"),
            "caller": (
                "{% include 'customer-order-limit-cancelled', cancelled_order: order %}"
                "{{ customer_order_limit_cancelled }}"
            ),
        }
        self.environment = Environment(loader=DictLoader(files))

    def cancelled(self, order: dict) -> str:
        return self.environment.get_template("caller").render(order=order).strip()

    def test_native_zero_keeps_to_pay_order_live_even_with_cancelled_fallback_text(self) -> None:
        order = {
            "is_cancelled": 0,
            "cancelled": True,
            "cancelled_at": "2026-09-10T00:00:00Z",
            "status": "cancelled",
            "financial_status_label": "Cancelled",
            "fulfillment_status_label": "Cancelled",
        }
        self.assertEqual(self.cancelled(order), "false")

    def test_native_one_still_cancels_order(self) -> None:
        self.assertEqual(
            self.cancelled({"is_cancelled": 1, "status": "to_pay"}),
            "true",
        )

    def test_fallback_signals_still_work_when_native_flag_is_absent(self) -> None:
        self.assertEqual(self.cancelled({"cancelled": True}), "true")
        self.assertEqual(self.cancelled({"status": "cancelled"}), "true")
        self.assertEqual(self.cancelled({"status": "to_pay"}), "false")


if __name__ == "__main__":
    unittest.main()
