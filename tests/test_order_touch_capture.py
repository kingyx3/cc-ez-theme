from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CAPTURE = ROOT / "theme" / "snippets" / "attribution-click-id.liquid"


class OrderTouchCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = CAPTURE.read_text(encoding="utf-8")

    def test_logged_in_customer_id_is_the_only_customer_scalar_sent(self) -> None:
        self.assertIn("customer.id | default: '' | json", self.source)
        self.assertNotIn("customer.email", self.source)
        self.assertNotIn("customer.phone", self.source)
        self.assertNotIn("customer.name", self.source)

    def test_latest_click_is_bound_to_the_order_touch_endpoint(self) -> None:
        self.assertIn("https://go.cardboard.sg/touch", self.source)
        self.assertIn("customer_id: String(customerId)", self.source)
        self.assertIn("click_id: clickId", self.source)
        self.assertIn("bindTouch(clickId)", self.source)

    def test_binding_is_retryable_and_idempotence_is_cached_per_customer_click(self) -> None:
        self.assertIn("'cc:order-touch:' + String(customerId) + ':' + clickId", self.source)
        self.assertIn("window.localStorage.setItem(key, '1')", self.source)
        self.assertIn("keepalive: true", self.source)

    def test_acquisition_handoff_name_is_unchanged(self) -> None:
        self.assertIn("window.ccSourceClickId = clickId || null;", self.source)


if __name__ == "__main__":
    unittest.main()
