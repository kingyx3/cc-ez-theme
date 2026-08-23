from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import easystore_hubspot_order_sync as production
import easystore_hubspot_orders as orders


class EasyStoreOrderCustomerIdTests(unittest.TestCase):
    def test_top_level_customer_id_wins(self) -> None:
        self.assertEqual(
            production.easystore_order_customer_id(
                {"customer_id": 123, "customer": {"id": 999}}
            ),
            "123",
        )

    def test_nested_customer_id_is_supported(self) -> None:
        self.assertEqual(
            production.easystore_order_customer_id({"customer": {"id": 456}}),
            "456",
        )

    def test_missing_customer_id_is_reported_as_missing(self) -> None:
        self.assertIsNone(production.easystore_order_customer_id({"id": 10}))


class RegisteredCustomerOrderAssociationTests(unittest.TestCase):
    def contact_index(
        self,
        mapping: dict[str, set[str]],
    ) -> orders.ContactIndex:
        return orders.ContactIndex(
            by_phone={},
            lifecycle_by_id={},
            by_email={},
            by_easystore_customer_id=mapping,
        )

    def test_registered_order_is_associated_by_easystore_customer_id(self) -> None:
        with (
            mock.patch.object(
                production,
                "hubspot_contact_index",
                return_value=self.contact_index({"7": {"contact-77"}}),
            ),
            mock.patch.object(
                orders,
                "hubspot_order_index",
                return_value={"10": "order-10"},
            ),
            mock.patch.object(
                orders,
                "iter_easystore_orders",
                return_value=iter([{"id": 10, "customer_id": 7}]),
            ),
            mock.patch.object(
                orders,
                "complete_order",
                side_effect=lambda _domain, _token, order: order,
            ),
            mock.patch.object(orders, "_associate_order") as associate,
        ):
            summary = production.ensure_registered_customer_order_associations(
                store_domain="cardboard.sg",
                easystore_access_token="easy-token",
                hubspot_access_token="hub-token",
                fallback_dial_code="65",
            )

        associate.assert_called_once_with(
            "hub-token",
            "order-10",
            "contact",
            "contact-77",
            orders.ORDER_CONTACT_ASSOCIATION_TYPE_ID,
        )
        self.assertEqual(summary["orders_with_easystore_customer_id"], 1)
        self.assertEqual(summary["order_customer_id_associations_ensured"], 1)
        self.assertEqual(summary["orders_without_easystore_customer_id"], 0)
        self.assertEqual(summary["orders_with_unmatched_easystore_customer_id"], 0)

    def test_missing_customer_id_is_visible_in_the_summary(self) -> None:
        with (
            mock.patch.object(
                production,
                "hubspot_contact_index",
                return_value=self.contact_index({}),
            ),
            mock.patch.object(orders, "hubspot_order_index", return_value={"10": "order-10"}),
            mock.patch.object(
                orders,
                "iter_easystore_orders",
                return_value=iter([{"id": 10}]),
            ),
            mock.patch.object(
                orders,
                "complete_order",
                side_effect=lambda _domain, _token, order: order,
            ),
            mock.patch.object(orders, "_associate_order") as associate,
        ):
            summary = production.ensure_registered_customer_order_associations(
                store_domain="cardboard.sg",
                easystore_access_token="easy-token",
                hubspot_access_token="hub-token",
                fallback_dial_code="65",
            )

        associate.assert_not_called()
        self.assertEqual(summary["orders_without_easystore_customer_id"], 1)
        self.assertEqual(summary["order_customer_id_associations_ensured"], 0)

    def test_ambiguous_customer_id_never_guesses(self) -> None:
        with (
            mock.patch.object(
                production,
                "hubspot_contact_index",
                return_value=self.contact_index({"7": {"contact-a", "contact-b"}}),
            ),
            mock.patch.object(
                orders,
                "hubspot_order_index",
                return_value={"10": "order-10"},
            ),
            mock.patch.object(
                orders,
                "iter_easystore_orders",
                return_value=iter([{"id": 10, "customer": {"id": 7}}]),
            ),
            mock.patch.object(
                orders,
                "complete_order",
                side_effect=lambda _domain, _token, order: order,
            ),
            mock.patch.object(orders, "_associate_order") as associate,
        ):
            summary = production.ensure_registered_customer_order_associations(
                store_domain="cardboard.sg",
                easystore_access_token="easy-token",
                hubspot_access_token="hub-token",
                fallback_dial_code="65",
            )

        associate.assert_not_called()
        self.assertEqual(summary["orders_with_ambiguous_easystore_customer_id"], 1)


if __name__ == "__main__":
    unittest.main()
