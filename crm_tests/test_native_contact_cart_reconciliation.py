from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import easystore_hubspot_checkout_sync as checkout_sync
import easystore_hubspot_customer_sync as customer_sync


class NativeDateOfBirthTests(unittest.TestCase):
    def test_writable_native_string_date_of_birth_is_detected(self) -> None:
        schema = {
            "name": "date_of_birth",
            "type": "string",
            "archived": False,
            "modificationMetadata": {"readOnlyValue": False},
        }
        with mock.patch.object(customer_sync.base, "_http_json", return_value=schema):
            self.assertEqual(
                customer_sync.native_date_of_birth_storage_type("hs"),
                "string",
            )

    def test_read_only_native_date_of_birth_is_not_claimed(self) -> None:
        schema = {
            "name": "date_of_birth",
            "type": "string",
            "modificationMetadata": {"readOnlyValue": True},
        }
        with mock.patch.object(customer_sync.base, "_http_json", return_value=schema):
            self.assertIsNone(customer_sync.native_date_of_birth_storage_type("hs"))

    def test_string_native_suppresses_easystore_birthday_fallback(self) -> None:
        with mock.patch.object(
            customer_sync,
            "_BASE_RESOLVE_CONTACT_FIELDS",
            return_value={
                "birthday": "easystore_customer_birthday",
                "tags": "easystore_customer_tags",
            },
        ), mock.patch.object(customer_sync, "_NATIVE_DOB_STRING", True):
            resolved = customer_sync.resolve_contact_fields("hs")

        self.assertEqual(resolved, {"tags": "easystore_customer_tags"})

    def test_real_birthdate_is_written_to_native_string_property(self) -> None:
        customer = {
            "id": 7,
            "birthdate": "1993-04-20",
            "birthday": "2027-04-20",
        }
        with mock.patch.object(customer_sync, "_NATIVE_DOB_STRING", True):
            properties = customer_sync.customer_properties(
                customer,
                "+6591234567",
                {},
                {},
            )

        self.assertEqual(properties["date_of_birth"], "1993-04-20")
        self.assertNotIn("easystore_customer_birthday", properties)

    def test_next_birthday_occurrence_is_not_written_as_date_of_birth(self) -> None:
        with mock.patch.object(customer_sync, "_NATIVE_DOB_STRING", True):
            properties = customer_sync.customer_properties(
                {"id": 7, "birthday": "2027-01-15"},
                "+6591234567",
                {},
                {},
            )

        self.assertNotIn("date_of_birth", properties)
        self.assertNotIn("easystore_customer_birthday", properties)


class ConvertedCartReconciliationTests(unittest.TestCase):
    def test_linked_order_marks_existing_cart_not_abandoned(self) -> None:
        calls: list[tuple[str, str, dict]] = []

        def fake_http(url: str, *, method: str = "GET", payload=None, **kwargs):
            calls.append((url, method, payload or {}))
            return {}

        with mock.patch.object(
            checkout_sync,
            "_BASE_LINK_CARTS_TO_ORDERS",
            return_value=1,
        ) as base_link, mock.patch.object(
            checkout_sync.commerce,
            "_http_json",
            side_effect=fake_http,
        ):
            linked = checkout_sync.link_carts_to_orders_and_reconcile(
                orders=[{"id": 42, "cart_token": "cart-abc"}],
                hubspot_access_token="hs",
                carts_by_token={"cart-abc": "cart-100"},
                hubspot_orders={"42": "order-200"},
            )

        self.assertEqual(linked, 1)
        base_link.assert_called_once()
        self.assertEqual(len(calls), 1)
        url, method, payload = calls[0]
        self.assertTrue(url.endswith("/cart-100"))
        self.assertEqual(method, "PATCH")
        self.assertEqual(
            payload,
            {"properties": {"easystore_cart_is_abandoned": "false"}},
        )

    def test_cart_is_not_changed_without_a_resolved_hubspot_order(self) -> None:
        with mock.patch.object(
            checkout_sync,
            "_BASE_LINK_CARTS_TO_ORDERS",
            return_value=0,
        ), mock.patch.object(checkout_sync.commerce, "_http_json") as http:
            linked = checkout_sync.link_carts_to_orders_and_reconcile(
                orders=[{"id": 42, "cart_token": "cart-abc"}],
                hubspot_access_token="hs",
                carts_by_token={"cart-abc": "cart-100"},
                hubspot_orders={},
            )

        self.assertEqual(linked, 0)
        http.assert_not_called()

    def test_same_cart_is_reconciled_once_if_duplicate_order_rows_are_seen(self) -> None:
        with mock.patch.object(
            checkout_sync,
            "_BASE_LINK_CARTS_TO_ORDERS",
            return_value=2,
        ), mock.patch.object(checkout_sync.commerce, "_http_json", return_value={}) as http:
            checkout_sync.link_carts_to_orders_and_reconcile(
                orders=[
                    {"id": 42, "cart_token": "cart-abc"},
                    {"id": 42, "cart_token": "cart-abc"},
                ],
                hubspot_access_token="hs",
                carts_by_token={"cart-abc": "cart-100"},
                hubspot_orders={"42": "order-200"},
            )

        http.assert_called_once()


if __name__ == "__main__":
    unittest.main()
