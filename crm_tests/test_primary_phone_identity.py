from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import easystore_hubspot_contact_identity as contact_identity
import easystore_hubspot_contact_repair as contact_repair
import easystore_hubspot_customer_sync as customer_sync
import easystore_hubspot_preflight as preflight
import easystore_hubspot_sync as base


class PrimaryPhonePreflightTests(unittest.TestCase):
    def test_secondary_mobilephone_does_not_create_a_false_duplicate(self) -> None:
        easystore = [
            {"id": 1, "phone": "9123 4567", "country_code": "SG"},
        ]
        hubspot = [
            {"id": "100", "properties": {"phone": "+6591234567"}},
            {"id": "200", "properties": {"mobilephone": "+6591234567"}},
        ]

        with mock.patch.object(preflight, "check_api_access", lambda **_: None), mock.patch.object(
            preflight,
            "repair_form_duplicates",
            lambda **_: {
                "hubspot_normalized_phone_collisions_seen": 0,
                "hubspot_form_duplicates_merged": 0,
                "hubspot_phone_collisions_left_for_preflight": 0,
            },
        ), mock.patch.object(
            preflight,
            "iter_easystore_customers",
            lambda *args, **kwargs: iter(easystore),
        ), mock.patch.object(
            preflight,
            "iter_hubspot_contacts",
            lambda *args, **kwargs: iter(hubspot),
        ):
            summary = preflight.check_identity(
                store_domain="shop.example",
                easystore_access_token="es",
                hubspot_access_token="hs",
                fallback_dial_code="65",
            )

        self.assertEqual(summary["ambiguous_hubspot_mobile_numbers"], 0)
        self.assertEqual(summary["hubspot_contact_identity_property"], "phone")

    def test_duplicate_primary_phone_still_fails_closed_after_repair_pass(self) -> None:
        easystore = [
            {"id": 1, "phone": "9123 4567", "country_code": "SG"},
        ]
        hubspot = [
            {"id": "100", "properties": {"phone": "+6591234567"}},
            {"id": "200", "properties": {"phone": "+65 9123 4567"}},
        ]

        with mock.patch.object(preflight, "check_api_access", lambda **_: None), mock.patch.object(
            preflight,
            "repair_form_duplicates",
            lambda **_: {
                "hubspot_normalized_phone_collisions_seen": 1,
                "hubspot_form_duplicates_merged": 0,
                "hubspot_phone_collisions_left_for_preflight": 1,
            },
        ), mock.patch.object(
            preflight,
            "iter_easystore_customers",
            lambda *args, **kwargs: iter(easystore),
        ), mock.patch.object(
            preflight,
            "iter_hubspot_contacts",
            lambda *args, **kwargs: iter(hubspot),
        ):
            with self.assertRaisesRegex(base.SyncError, "after the safe form-duplicate repair"):
                preflight.check_identity(
                    store_domain="shop.example",
                    easystore_access_token="es",
                    hubspot_access_token="hs",
                    fallback_dial_code="65",
                )


class FormDuplicateRepairTests(unittest.TestCase):
    def _integration(self) -> dict:
        return {
            "id": "539244172021",
            "properties": {
                "phone": "+6591735876",
                "mobilephone": "+6591735876",
                "easystore_customer_id": "41900089",
                "hs_object_source_label": "INTEGRATION",
                "hs_object_source_detail_1": "EasyStore_Integration",
            },
        }

    def _form(self) -> dict:
        return {
            "id": "539344382693",
            "properties": {
                "phone": "6591735876",
                "email": "shopper@example.com",
                "hs_object_source_label": "FORM",
                "hs_object_source_detail_1": "#details_form",
            },
        }

    def test_exact_observed_integration_plus_form_shape_is_mergeable(self) -> None:
        pair = contact_repair.safe_form_merge_pair(
            customer_id="41900089",
            normalized_phone="+6591735876",
            contacts=[self._integration(), self._form()],
        )
        self.assertEqual(pair, ("539244172021", "539344382693"))

    def test_form_contact_without_email_is_not_auto_merged(self) -> None:
        form = self._form()
        form["properties"].pop("email")
        self.assertIsNone(
            contact_repair.safe_form_merge_pair(
                customer_id="41900089",
                normalized_phone="+6591735876",
                contacts=[self._integration(), form],
            )
        )

    def test_two_integration_records_are_not_auto_merged(self) -> None:
        duplicate = self._integration()
        duplicate["id"] = "200"
        self.assertIsNone(
            contact_repair.safe_form_merge_pair(
                customer_id="41900089",
                normalized_phone="+6591735876",
                contacts=[self._integration(), duplicate],
            )
        )

    def test_wrong_easystore_customer_id_is_not_auto_merged(self) -> None:
        self.assertIsNone(
            contact_repair.safe_form_merge_pair(
                customer_id="different",
                normalized_phone="+6591735876",
                contacts=[self._integration(), self._form()],
            )
        )

    def test_repair_calls_hubspot_merge_with_integration_as_primary(self) -> None:
        calls: list[tuple[str, str, dict]] = []

        def fake_http(url: str, *, method: str = "GET", headers=None, payload=None, **kwargs):
            calls.append((url, method, payload or {}))
            return {"id": "merged"}

        easystore = [{"id": "41900089", "phone": "91735876", "country_code": "SG"}]
        with mock.patch.object(
            contact_repair.base,
            "iter_easystore_customers",
            lambda *args, **kwargs: iter(easystore),
        ), mock.patch.object(
            contact_repair,
            "iter_hubspot_contacts_for_repair",
            lambda _token: iter([self._integration(), self._form()]),
        ), mock.patch.object(contact_repair.base, "_http_json", fake_http):
            summary = contact_repair.repair_form_duplicates(
                store_domain="shop.example",
                easystore_access_token="es",
                hubspot_access_token="hs",
                fallback_dial_code="65",
            )

        self.assertEqual(summary["hubspot_form_duplicates_merged"], 1)
        merge_calls = [call for call in calls if call[0].endswith("/merge")]
        self.assertEqual(len(merge_calls), 1)
        self.assertEqual(merge_calls[0][1], "POST")
        self.assertEqual(
            merge_calls[0][2],
            {
                "primaryObjectId": "539244172021",
                "objectIdToMerge": "539344382693",
            },
        )


class PrimaryPhoneCustomerSyncTests(unittest.TestCase):
    def test_production_contact_reader_removes_mobilephone_from_identity_input(self) -> None:
        contacts = [
            {
                "id": "100",
                "properties": {
                    "phone": "+6591234567",
                    "mobilephone": "+6599999999",
                    "email": "shopper@example.com",
                },
            }
        ]

        with mock.patch.object(
            customer_sync,
            "_BASE_ITER_HUBSPOT_CONTACTS",
            lambda _token: iter(contacts),
        ):
            result = list(customer_sync.iter_hubspot_contacts_by_primary_phone("hs"))

        properties = result[0]["properties"]
        self.assertEqual(properties["phone"], "+6591234567")
        self.assertEqual(properties["email"], "shopper@example.com")
        self.assertNotIn("mobilephone", properties)

        # The adapter must not mutate the HubSpot response object in place.
        self.assertEqual(contacts[0]["properties"]["mobilephone"], "+6599999999")

    def test_mobilephone_is_still_written_as_a_convenience_mirror(self) -> None:
        properties = base.customer_properties(
            {"id": 1, "first_name": "Ada"},
            "+6591234567",
        )
        self.assertEqual(properties["phone"], "+6591234567")
        self.assertEqual(properties["mobilephone"], "+6591234567")


class PrimaryPhoneCommerceIdentityTests(unittest.TestCase):
    def test_orders_and_carts_index_only_hubspot_phone(self) -> None:
        seen_properties: list[str] = []
        contacts = [
            {
                "id": "100",
                "properties": {
                    "phone": "+6591234567",
                    "email": "buyer@example.com",
                    "easystore_customer_id": "7",
                    "lifecyclestage": "lead",
                },
            },
            {
                "id": "200",
                "properties": {
                    "mobilephone": "+6591234567",
                    "email": "other@example.com",
                },
            },
        ]

        def fake_iter(_url: str, _token: str, properties: str):
            seen_properties.append(properties)
            return iter(contacts)

        with mock.patch.object(
            contact_identity.orders,
            "iter_hubspot_objects",
            fake_iter,
        ):
            index = contact_identity.hubspot_contact_index("hs", "65")

        self.assertEqual(index.by_phone["+6591234567"], {"100"})
        self.assertEqual(index.by_easystore_customer_id["7"], {"100"})
        self.assertEqual(index.by_email["buyer@example.com"], {"100"})
        self.assertEqual(index.lifecycle_by_id["100"], "lead")
        self.assertNotIn("mobilephone", seen_properties[0])


if __name__ == "__main__":
    unittest.main()
