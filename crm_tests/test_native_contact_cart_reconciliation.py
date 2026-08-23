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


class ContactSourceDateTests(unittest.TestCase):
    def test_contact_source_dates_have_explicit_easystore_destinations(self) -> None:
        original = customer_sync.base.CONTACT_FIELDS
        try:
            customer_sync._install_contact_source_date_fields()
            fields = {field.key: field for field in customer_sync.base.CONTACT_FIELDS}
            created = fields["source_created_at"]
            modified = fields["source_modified_at"]

            self.assertEqual(created.fallback, "easystore_customer_created_at")
            self.assertEqual(created.sources[0], "created_at")
            self.assertEqual(modified.fallback, "easystore_customer_modified_at")
            self.assertEqual(modified.sources[0], "updated_at")
            self.assertEqual(created.native, ())
            self.assertEqual(modified.native, ())
        finally:
            customer_sync.base.CONTACT_FIELDS = original

    def test_legacy_customer_since_destination_is_no_longer_written(self) -> None:
        with mock.patch.object(
            customer_sync,
            "_BASE_RESOLVE_CONTACT_FIELDS",
            return_value={
                "customer_since": "easystore_customer_since",
                "source_created_at": "easystore_customer_created_at",
                "source_modified_at": "easystore_customer_modified_at",
            },
        ), mock.patch.object(customer_sync, "_NATIVE_DOB_STRING", False):
            resolved = customer_sync.resolve_contact_fields("hs")

        self.assertNotIn("customer_since", resolved)
        self.assertEqual(
            resolved["source_created_at"],
            "easystore_customer_created_at",
        )
        self.assertEqual(
            resolved["source_modified_at"],
            "easystore_customer_modified_at",
        )

    def test_customer_field_values_use_easystore_created_and_updated_timestamps(self) -> None:
        original = customer_sync.base.CONTACT_FIELDS
        try:
            customer_sync._install_contact_source_date_fields()
            values = customer_sync.base.customer_field_values(
                {
                    "created_at": "2024-01-02T03:04:05Z",
                    "updated_at": "2024-06-07T08:09:10Z",
                }
            )
        finally:
            customer_sync.base.CONTACT_FIELDS = original

        self.assertIn("source_created_at", values)
        self.assertIn("source_modified_at", values)
        self.assertNotEqual(values["source_created_at"], values["source_modified_at"])


class NativeCartStatusTests(unittest.TestCase):
    def test_open_unpaid_checkout_uses_native_abandoned_status(self) -> None:
        with mock.patch.object(
            checkout_sync,
            "_BASE_CART_PROPERTIES",
            return_value={
                "hs_external_status": "unpaid",
                "easystore_cart_is_abandoned": "true",
            },
        ), mock.patch.object(
            checkout_sync.commerce,
            "is_abandoned",
            return_value=True,
        ):
            properties = checkout_sync.cart_properties_with_native_status(
                {"financial_status": "unpaid"},
                cart_token="cart-abc",
                store_domain="shop.example",
                field_properties={"status": "hs_external_status"},
                fallback_dial_code="65",
            )

        self.assertEqual(properties["hs_external_status"], "Abandoned")
        self.assertEqual(properties["easystore_cart_is_abandoned"], "true")

    def test_recovered_checkout_uses_native_recovered_status(self) -> None:
        with mock.patch.object(
            checkout_sync,
            "_BASE_CART_PROPERTIES",
            return_value={
                "hs_external_status": "recovered",
                "easystore_cart_is_abandoned": "false",
            },
        ), mock.patch.object(
            checkout_sync.commerce,
            "is_abandoned",
            return_value=False,
        ):
            properties = checkout_sync.cart_properties_with_native_status(
                {"financial_status": "recovered"},
                cart_token="cart-abc",
                store_domain="shop.example",
                field_properties={"status": "hs_external_status"},
                fallback_dial_code="65",
            )

        self.assertEqual(properties["hs_external_status"], "Recovered")
        self.assertEqual(properties["easystore_cart_is_abandoned"], "false")

    def test_non_native_status_fallback_is_not_rewritten(self) -> None:
        with mock.patch.object(
            checkout_sync,
            "_BASE_CART_PROPERTIES",
            return_value={"easystore_cart_status": "unpaid"},
        ), mock.patch.object(
            checkout_sync.commerce,
            "is_abandoned",
            return_value=True,
        ):
            properties = checkout_sync.cart_properties_with_native_status(
                {"financial_status": "unpaid"},
                cart_token="cart-abc",
                store_domain="shop.example",
                field_properties={"status": "easystore_cart_status"},
                fallback_dial_code="65",
            )

        self.assertEqual(properties["easystore_cart_status"], "unpaid")
        self.assertNotIn("hs_external_status", properties)


class CartSourceDateTests(unittest.TestCase):
    def test_cart_created_and_modified_dates_use_native_external_fields(self) -> None:
        original = checkout_sync.commerce.cart_mapping.CART_FIELDS
        try:
            checkout_sync._install_native_cart_source_date_fields()
            fields = {
                field.key: field
                for field in checkout_sync.commerce.cart_mapping.CART_FIELDS
            }
            created = fields["created_at"]
            modified = fields["modified_at"]
            abandoned = fields["abandoned_at"]

            self.assertEqual(created.native, ("hs_external_created_date",))
            self.assertEqual(modified.native, ("hs_external_modified_date",))
            self.assertEqual(modified.sources[0], "updated_at")
            self.assertEqual(abandoned.native, ())
            self.assertEqual(abandoned.sources, ("abandoned_at",))
            self.assertEqual(abandoned.fallback, "easystore_cart_abandoned_at")
        finally:
            checkout_sync.commerce.cart_mapping.CART_FIELDS = original

    def test_admin_checkout_preserves_source_modified_and_abandoned_timestamps(self) -> None:
        with mock.patch.object(
            checkout_sync,
            "_BASE_ADMIN_AS_CHECKOUT",
            return_value={"created_at": "2024-01-02T03:04:05Z"},
        ):
            checkout = checkout_sync.admin_checkout_with_source_dates(
                {
                    "updated_at": "2024-06-07T08:09:10Z",
                    "abandoned_at": "2024-06-01T02:03:04Z",
                }
            )

        self.assertEqual(checkout["updated_at"], "2024-06-07T08:09:10Z")
        self.assertEqual(checkout["abandoned_at"], "2024-06-01T02:03:04Z")


class ConvertedCartReconciliationTests(unittest.TestCase):
    def test_linked_order_marks_existing_cart_recovered_on_native_status(self) -> None:
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
            {
                "properties": {
                    "hs_external_status": "Recovered",
                    "easystore_cart_is_abandoned": "false",
                }
            },
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
