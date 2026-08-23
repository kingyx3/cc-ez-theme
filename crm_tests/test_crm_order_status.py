from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import easystore_hubspot_order_sync as production_orders
import easystore_hubspot_orders as orders


class HubSpotOrderStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_fields = orders.ORDER_FIELDS
        self.original_derivations = dict(orders.ORDER_FIELD_DERIVATIONS)
        self.original_defaults = dict(orders.DEFAULT_ORDER_FIELD_PROPERTIES)
        production_orders.configure_order_status_mapping()

    def tearDown(self) -> None:
        orders.ORDER_FIELDS = self.original_fields
        orders.ORDER_FIELD_DERIVATIONS.clear()
        orders.ORDER_FIELD_DERIVATIONS.update(self.original_derivations)
        orders.DEFAULT_ORDER_FIELD_PROPERTIES = self.original_defaults

    def _properties(self, order: dict[str, object]) -> dict[str, str]:
        return orders.order_properties(
            order,
            external_id="1001",
            store_domain="cardboardcollective.easy.co",
        )

    def test_production_mapping_targets_hubspots_actual_status_property(self) -> None:
        status_field = next(field for field in orders.ORDER_FIELDS if field.key == "order_status")
        self.assertEqual(status_field.native, ("hs_external_order_status",))
        self.assertEqual(
            orders.DEFAULT_ORDER_FIELD_PROPERTIES["order_status"],
            "hs_external_order_status",
        )

    def test_paid_order_populates_native_hubspot_status(self) -> None:
        mapped = self._properties(
            {
                "status": "open",
                "financial_status_label": "Paid",
                "fulfillment_status": "unfulfilled",
            }
        )
        self.assertEqual(mapped["hs_external_order_status"], "Paid")
        self.assertNotIn("hs_order_status", mapped)

    def test_fulfilled_state_wins_over_paid(self) -> None:
        mapped = self._properties(
            {
                "status": "open",
                "financial_status": "paid",
                "fulfillment_status": "fulfilled",
            }
        )
        self.assertEqual(mapped["hs_external_order_status"], "fulfilled")

    def test_cancelled_state_wins_over_paid(self) -> None:
        mapped = self._properties(
            {
                "status": "cancelled",
                "financial_status": "paid",
                "fulfillment_status": "unfulfilled",
            }
        )
        self.assertEqual(mapped["hs_external_order_status"], "cancelled")

    def test_refunded_state_wins_even_when_order_is_cancelled(self) -> None:
        mapped = self._properties(
            {
                "status": "cancelled",
                "financial_status_label": "Refunded",
                "fulfillment_status": "restocked",
            }
        )
        self.assertEqual(mapped["hs_external_order_status"], "Refunded")

    def test_partial_fulfilment_is_preserved_from_easystore(self) -> None:
        mapped = self._properties(
            {
                "status": "open",
                "financial_status": "paid",
                "fulfillment_status": "partially_fulfilled",
            }
        )
        self.assertEqual(
            mapped["hs_external_order_status"],
            "partially_fulfilled",
        )

    def test_cancelled_flag_is_used_when_order_status_is_missing(self) -> None:
        mapped = self._properties(
            {
                "is_cancelled": True,
                "financial_status": "paid",
                "fulfillment_status": "unfulfilled",
            }
        )
        self.assertEqual(mapped["hs_external_order_status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
