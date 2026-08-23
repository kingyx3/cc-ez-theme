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

    def test_cancelled_state_wins_over_refund(self) -> None:
        mapped = self._properties(
            {
                "status": "cancelled",
                "financial_status_label": "Refunded",
                "fulfillment_status": "restocked",
            }
        )
        self.assertEqual(mapped["hs_external_order_status"], "cancelled")

    def test_refunded_state_is_used_when_order_is_not_cancelled(self) -> None:
        mapped = self._properties(
            {
                "status": "closed",
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

    def test_every_known_cancellation_flag_shape_is_detected(self) -> None:
        signals = (
            {"is_cancelled": True},
            {"is_cancelled": 1},
            {"is_cancelled": "1"},
            {"cancelled": True},
            {"cancelled": 1},
            {"canceled": "true"},
        )
        for signal in signals:
            with self.subTest(signal=signal):
                mapped = self._properties(
                    {
                        "status": "open",
                        "financial_status": "paid",
                        "fulfillment_status": "unfulfilled",
                        **signal,
                    }
                )
                self.assertEqual(mapped["hs_external_order_status"], "cancelled")

    def test_cancellation_timestamp_is_detected(self) -> None:
        for key in ("cancelled_at", "canceled_at", "cancellation_date"):
            with self.subTest(key=key):
                mapped = self._properties(
                    {
                        "status": "open",
                        "financial_status": "paid",
                        "fulfillment_status": "unfulfilled",
                        key: "2026-08-23T10:20:30+08:00",
                    }
                )
                self.assertEqual(mapped["hs_external_order_status"], "cancelled")

    def test_cancelled_payment_or_fulfillment_label_is_detected(self) -> None:
        for signal in (
            {"financial_status_label": "Cancelled"},
            {"financial_status": "canceled"},
            {"fulfillment_status_label": "Cancelled"},
            {"fulfillment_status": "canceled"},
        ):
            with self.subTest(signal=signal):
                mapped = self._properties({"status": "open", **signal})
                self.assertIn(
                    mapped["hs_external_order_status"].casefold(),
                    {"cancelled", "canceled"},
                )

    def test_false_cancellation_signals_do_not_cancel_an_order(self) -> None:
        for signal in (
            {"is_cancelled": False},
            {"is_cancelled": 0},
            {"cancelled": "false"},
            {"cancelled_at": "0"},
            {"cancelled_at": "null"},
        ):
            with self.subTest(signal=signal):
                mapped = self._properties(
                    {
                        "status": "open",
                        "financial_status": "paid",
                        "fulfillment_status": "unfulfilled",
                        **signal,
                    }
                )
                self.assertEqual(mapped["hs_external_order_status"], "paid")


class HubSpotShippingRecipientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_fields = orders.ORDER_FIELDS
        self.original_defaults = dict(orders.DEFAULT_ORDER_FIELD_PROPERTIES)
        production_orders.configure_shipping_recipient_mapping()

    def tearDown(self) -> None:
        orders.ORDER_FIELDS = self.original_fields
        orders.DEFAULT_ORDER_FIELD_PROPERTIES = self.original_defaults

    def test_shipping_recipient_uses_native_shipping_address_customer_name(self) -> None:
        recipient_field = next(
            field for field in orders.ORDER_FIELDS if field.key == "shipping_recipient"
        )
        self.assertEqual(recipient_field.native, ("hs_shipping_address_name",))
        self.assertIsNone(recipient_field.fallback)
        self.assertEqual(
            orders.DEFAULT_ORDER_FIELD_PROPERTIES["shipping_recipient"],
            "hs_shipping_address_name",
        )

        mapped = orders.order_properties(
            {
                "shipping_address": {
                    "name": "Reception Desk",
                    "address1": "1 Example Road",
                    "city": "Singapore",
                }
            },
            external_id="1002",
            store_domain="cardboardcollective.easy.co",
        )
        self.assertEqual(mapped["hs_shipping_address_name"], "Reception Desk")
        self.assertNotIn("easystore_shipping_recipient", mapped)


if __name__ == "__main__":
    unittest.main()
